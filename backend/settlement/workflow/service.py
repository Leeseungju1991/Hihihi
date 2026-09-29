"""정산 워크플로 — 대조 실행, 자동화(미리보기→실행→자동 재검증), 재검증, 보류, 예외, 확정.

운영 원천은 SourceRepository(읽기 전용)로만 접근하고, 모든 쓰기는 별도 저장소(보정·예외·보류·이력)에만 한다.
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field, replace
from typing import Callable, Dict, List, Optional, Sequence

from ..config import RuleConfig
from ..domain.models import (
    Adjustment,
    Approval,
    Category,
    ErrorCase,
    Evidence,
    ExceptionStatus,
    Hold,
    PlantResult,
    ReconcileRun,
    RecheckRecord,
    SettlementException,
    SourceBundle,
)
from ..domain.validation import ValidationError, validate_exception, validate_month
from ..engine.ledger import effective_adjustments
from ..engine.reconcile import Evaluation, reconcile, signature, simulate
from ..llm.explainer import Explainer, RuleBasedExplainer
from ..ports import Repositories


class MonthLockedError(Exception):
    """확정된 정산월 수정 시도."""


class NotFoundError(LookupError):
    pass


class ConfirmationRequired(Exception):
    """확정 시 경고 — acknowledge=True 로 다시 호출해야 한다."""

    def __init__(self, warnings: List[str], open_holds: List[str], unresolved: List[str]):
        super().__init__("; ".join(warnings))
        self.warnings = warnings
        self.open_holds = open_holds
        self.unresolved = unresolved


@dataclass
class AdjustmentPreview:
    plant_id: str
    plant_name: str
    category_before: Category
    adjustments: List[Adjustment]
    kwh_before: str
    kwh_after: str
    implied_price_after: Optional[str]
    predicted_pass: bool
    remaining_issues: List[str] = field(default_factory=list)


@dataclass
class AutomationPreview:
    run_id: str
    month: str
    target_count: int
    formulas: List[str]
    items: List[AdjustmentPreview]


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class SettlementService:
    def __init__(
        self,
        repos: Repositories,
        explainer: Optional[Explainer] = None,
        cfg: Optional[RuleConfig] = None,
        clock: Callable[[], dt.datetime] = _now,
    ):
        self.repos = repos
        self.explainer = explainer or RuleBasedExplainer()
        self.cfg = cfg or RuleConfig()
        self.clock = clock

    # ─────────── 공통 ───────────
    def is_locked(self, month: str) -> bool:
        return self.repos.approvals.get(month) is not None

    def _ensure_known_plant(self, plant_id: str) -> None:
        if plant_id not in self.repos.source.plants():
            raise ValidationError({"plant_id": "발전소 마스터에 없는 발전소입니다"})

    def _ensure_unlocked(self, month: str) -> None:
        if self.is_locked(month):
            raise MonthLockedError("{} 정산월은 확정되어 수정할 수 없습니다".format(month))

    def _reconcile(self, month: str, bundle: Optional[SourceBundle] = None, only=None) -> List[PlantResult]:
        bundle = bundle or self.repos.source.load(month)
        return reconcile(
            bundle,
            exceptions=self.repos.exceptions.list(month=month),
            committed=self.repos.adjustments.list(month),
            holds=self.repos.holds.list(month),
            cfg=self.cfg,
            only=only,
            failed_signatures=self._failed_signatures(month),
        )

    def _failed_signatures(self, month: str) -> Dict[str, set]:
        out: Dict[str, set] = {}
        for rc in self.repos.rechecks.list(month):
            if rc.trigger == "AUTOMATION" and not rc.passed and rc.tried_signature:
                out.setdefault(rc.plant_id, set()).add(rc.tried_signature)
        return out

    # ─────────── ① 데이터 불러오기 ───────────
    def load_counts(self, month: str) -> Dict[str, int]:
        validate_month(month)
        return self.repos.source.load(month).counts()

    # ─────────── ③ 3자 대조 ───────────
    def run(self, month: str, actor: str) -> ReconcileRun:
        validate_month(month)
        self._ensure_unlocked(month)  # 확정 후 재대조로 확정 결과가 바뀌지 않게
        bundle = self.repos.source.load(month)
        run = ReconcileRun(
            run_id=uuid.uuid4().hex[:12],
            month=month,
            created_at=self.clock(),
            created_by=actor,
            counts=bundle.counts(),
            results=self._reconcile(month, bundle),
        )
        self.repos.runs.save(run)
        return run

    def latest_run(self, month: str) -> ReconcileRun:
        run = self.repos.runs.latest(month)
        if run is None:
            raise NotFoundError("{} 대조 실행 이력이 없습니다".format(month))
        return run

    def _get_run(self, run_id: str) -> ReconcileRun:
        run = self.repos.runs.get(run_id)
        if run is None:
            raise NotFoundError("run {} 없음".format(run_id))
        return run

    def _targets(self, run: ReconcileRun, plant_ids: Optional[Sequence[str]]) -> List[PlantResult]:
        wanted = set(plant_ids) if plant_ids else None
        return [
            r
            for r in run.results
            if r.category == Category.AUTOMATABLE and (wanted is None or r.plant_id in wanted)
        ]

    # ─────────── 자동화: 안내창(미리보기) ───────────
    def preview_automation(self, run_id: str, plant_ids: Optional[Sequence[str]] = None) -> AutomationPreview:
        run = self._get_run(run_id)
        bundle = self.repos.source.load(run.month)
        committed = self.repos.adjustments.list(run.month)
        items: List[AdjustmentPreview] = []
        formulas: List[str] = []
        for r in self._targets(run, plant_ids):
            after: Evaluation = simulate(r, bundle, committed, self.cfg)
            kinds = sorted({a.kind.value for a in r.candidate_adjustments})
            for k in kinds:
                if k not in formulas:
                    formulas.append(k)
            items.append(
                AdjustmentPreview(
                    plant_id=r.plant_id,
                    plant_name=r.plant_name,
                    category_before=r.category,
                    adjustments=r.candidate_adjustments,
                    kwh_before=str(r.invoice_kwh),
                    kwh_after=str(after.kwh_total),
                    implied_price_after=str(after.implied_price) if after.implied_price is not None else None,
                    predicted_pass=after.ok,
                    remaining_issues=list(after.messages),
                )
            )
        return AutomationPreview(run_id=run.run_id, month=run.month, target_count=len(items), formulas=formulas, items=items)

    # ─────────── 자동화: 실행 → 자동 재검증 ───────────
    def execute_automation(
        self, run_id: str, actor: str, plant_ids: Optional[Sequence[str]] = None
    ) -> List[RecheckRecord]:
        """발전소 단위 원자적 적용: 보정 기록 → 자동 재검증 → 통과면 유지, 미통과면 되돌림 기록.

        미통과 보정을 남겨두면 이후 등록한 예외와 이중으로 반영될 수 있으므로 되돌린다.
        되돌림도 append-only 행이므로 '시도했다가 되돌림' 이력이 감사용으로 남는다.
        """
        run = self._get_run(run_id)
        self._ensure_unlocked(run.month)
        now = self.clock()
        records: List[RecheckRecord] = []
        for r in self._targets(run, plant_ids):
            adjs = [replace(a, applied_by=actor, applied_at=now) for a in r.candidate_adjustments]
            self.repos.adjustments.add(adjs)
            rc = self.recheck(run.month, r.plant_id, actor, trigger="AUTOMATION", tried_signature=signature(adjs))
            if rc.passed:
                # 보정에 쓰인 예외는 '적용 중'으로 전환 (새 버전 행)
                for exc_id in sorted({a.exception_id for a in adjs if a.exception_id}):
                    exc = self.repos.exceptions.get(exc_id)
                    if exc and exc.status == ExceptionStatus.REGISTERED:
                        self._save_exception_version(exc, actor, status=ExceptionStatus.ACTIVE)
            else:
                self.repos.adjustments.add(
                    [
                        replace(
                            a,
                            adjustment_id=a.adjustment_id + "-R",
                            kwh_before=a.kwh_after,
                            kwh_after=a.kwh_before,
                            formula="재검증 미통과로 되돌림: " + a.formula,
                            reverts=a.adjustment_id,
                            applied_at=self.clock(),
                        )
                        for a in adjs
                    ]
                )
                self._refresh(run.month, r.plant_id)
            records.append(rc)
        return records

    # ─────────── 재검증 ───────────
    def recheck(
        self, month: str, plant_id: str, actor: str, trigger: str = "MANUAL", tried_signature: str = ""
    ) -> RecheckRecord:
        self._ensure_unlocked(month)
        results = self._reconcile(month, only={plant_id})
        if not results:
            raise NotFoundError("{} {} 대조 대상 아님".format(month, plant_id))
        result = results[0]
        passed = result.category == Category.PASS
        if passed:
            cause, action, evidence = "", "", list(result.evidence)
        else:
            exp = self.explainer.explain(result)
            cause, action, evidence = exp.cause, exp.recommended_action, exp.evidence

        attempt = len(self.repos.rechecks.list(month, plant_id)) + 1
        record = RecheckRecord(
            month=month,
            plant_id=plant_id,
            attempt=attempt,
            passed=passed,
            category=result.category,
            cause=cause,
            recommended_action=action,
            evidence=evidence,
            actor=actor,
            at=self.clock(),
            trigger=trigger,
            tried_signature=tried_signature,
        )
        self.repos.rechecks.add(record)

        # 최신 대조 결과에 반영
        run = self.repos.runs.latest(month)
        if run is not None:
            run.results = [result if x.plant_id == plant_id else x for x in run.results]
            self.repos.runs.save(run)
        return record

    def explain(self, month: str, plant_id: str):
        run = self.latest_run(month)
        for r in run.results:
            if r.plant_id == plant_id:
                return r, self.explainer.explain(r)
        raise NotFoundError(plant_id)

    # ─────────── 보류 ───────────
    def hold(self, month: str, plant_id: str, reason: str, actor: str) -> Hold:
        self._ensure_unlocked(month)
        if not reason or not reason.strip():
            raise ValidationError({"reason": "보류 사유는 필수입니다"})
        self._ensure_known_plant(plant_id)
        h = Hold(month=month, plant_id=plant_id, reason=reason.strip(), actor=actor, at=self.clock())
        self.repos.holds.save(h)
        self._refresh(month, plant_id)
        return h

    def release_hold(self, month: str, plant_id: str, actor: str) -> RecheckRecord:
        """보류 해제 = 재검증으로 복귀."""
        self._ensure_unlocked(month)
        current = [h for h in self.repos.holds.list(month) if h.plant_id == plant_id and not h.released]
        if not current:
            raise NotFoundError("보류 중이 아닙니다")
        h = current[0]
        self.repos.holds.save(replace(h, released=True, released_by=actor, released_at=self.clock()))
        return self.recheck(month, plant_id, actor, trigger="MANUAL")

    def _refresh(self, month: str, plant_id: str) -> None:
        run = self.repos.runs.latest(month)
        if run is None:
            return
        fresh = self._reconcile(month, only={plant_id})
        if fresh:
            run.results = [fresh[0] if x.plant_id == plant_id else x for x in run.results]
            self.repos.runs.save(run)

    # ─────────── ② 예외 관리 ───────────
    def create_exception(self, exc: SettlementException, actor: str) -> SettlementException:
        self._ensure_unlocked(exc.month)
        validate_exception(exc, known_plants=self.repos.source.plants())
        exc.exception_id = exc.exception_id or "EX-" + uuid.uuid4().hex[:8].upper()
        if self.repos.exceptions.get(exc.exception_id) is not None:
            raise ValidationError({"exception_id": "이미 존재하는 예외 번호"})
        exc.version = 1
        exc.updated_by = actor
        exc.updated_at = self.clock()
        self.repos.exceptions.save(exc)
        return exc

    def update_exception(self, exc: SettlementException, actor: str) -> SettlementException:
        cur = self.repos.exceptions.get(exc.exception_id)
        if cur is None:
            raise NotFoundError(exc.exception_id)
        self._ensure_unlocked(cur.month)
        self._ensure_unlocked(exc.month)
        if cur.status == ExceptionStatus.CLOSED:
            raise ValidationError({"status": "종료된 예외는 수정할 수 없습니다"})
        validate_exception(exc, known_plants=self.repos.source.plants())
        return self._save_exception_version(exc, actor, base_version=cur.version)

    def close_exception(self, exception_id: str, actor: str) -> SettlementException:
        cur = self.repos.exceptions.get(exception_id)
        if cur is None:
            raise NotFoundError(exception_id)
        self._ensure_unlocked(cur.month)
        return self._save_exception_version(cur, actor, status=ExceptionStatus.CLOSED)

    def _save_exception_version(
        self,
        exc: SettlementException,
        actor: str,
        status: Optional[ExceptionStatus] = None,
        base_version: Optional[int] = None,
    ) -> SettlementException:
        base = base_version if base_version is not None else exc.version
        new = replace(
            exc,
            version=base + 1,
            status=status or exc.status,
            updated_by=actor,
            updated_at=self.clock(),
        )
        self.repos.exceptions.save(new)
        return new

    # ─────────── 에러 케이스 ───────────
    def add_error_case(self, case: ErrorCase, actor: str) -> ErrorCase:
        if not case.symptom.strip():
            raise ValidationError({"symptom": "증상은 필수입니다"})
        validate_month(case.month)
        self._ensure_known_plant(case.plant_id)
        existing = self.repos.error_cases.list()
        case.case_no = case.case_no or "ERR-{:04d}".format(len(existing) + 1)
        case.created_by = actor
        self.repos.error_cases.add(case)
        return case

    # ─────────── 최종 확정 ───────────
    def finalize_check(self, month: str) -> Dict[str, List[str]]:
        """확정 전 사전 점검 — 화면이 경고창을 먼저 띄울 수 있게 한다."""
        run = self.latest_run(month)
        open_holds = [h.plant_id for h in self.repos.holds.list(month) if not h.released]
        unresolved = [
            r.plant_id
            for r in run.results
            if r.category in (Category.AUTOMATABLE, Category.REVIEW, Category.ERROR)
        ]
        warnings: List[str] = []
        if open_holds:
            warnings.append("보류 {}건이 남아 있습니다".format(len(open_holds)))
        if unresolved:
            warnings.append("미해결(자동화·확인·에러) {}건이 남아 있습니다".format(len(unresolved)))
        return {"warnings": warnings, "open_holds": open_holds, "unresolved": unresolved}

    def finalize(self, month: str, actor: str, acknowledge: bool = False, note: str = "") -> Approval:
        self._ensure_unlocked(month)
        check = self.finalize_check(month)
        if check["warnings"] and not acknowledge:
            raise ConfirmationRequired(check["warnings"], check["open_holds"], check["unresolved"])
        approval = Approval(month=month, actor=actor, at=self.clock(), open_holds=check["open_holds"], note=note)
        self.repos.approvals.add(approval)
        return approval

    # ─────────── 확인 대상 상세 ───────────
    def plant_detail(self, month: str, plant_id: str) -> Dict[str, object]:
        run = self.latest_run(month)
        result = next((r for r in run.results if r.plant_id == plant_id), None)
        if result is None:
            raise NotFoundError(plant_id)
        exp = self.explainer.explain(result) if result.category != Category.PASS else None
        return {
            "result": result,
            "explanation": exp,
            "rechecks": self.repos.rechecks.list(month, plant_id),
            "holds": self.repos.holds.history(month, plant_id),
            "exceptions": self.repos.exceptions.list(month=month, plant_id=plant_id),
            "adjustments": [
                a for a in effective_adjustments(self.repos.adjustments.list(month)) if a.plant_id == plant_id
            ],
        }


def evidence_dict(evidence: List[Evidence]) -> List[Dict[str, str]]:
    return [{"key": e.key, "label": e.label, "value": e.value} for e in evidence]
