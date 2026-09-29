"""⑤ 리포트 데이터. 렌더링(화면·PDF)은 프론트가 한다 — 여기서는 JSON 구조만 만든다.

- kind="monthly"   : 정산월 종합 (월 1회)
- kind="unresolved": 미결 건 즉시 발행 (확인·에러·보류만)
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..domain.models import Basis, Category
from ..engine.reconcile import tag_label
from ..workflow.service import SettlementService, evidence_dict


def _dec(v) -> Optional[str]:
    return None if v is None else str(v)


def build_report(svc: SettlementService, month: str, kind: str = "monthly") -> Dict[str, Any]:
    run = svc.latest_run(month)
    repos = svc.repos
    adjustments = repos.adjustments.list(month)
    rechecks = repos.rechecks.list(month)
    holds = repos.holds.list(month)
    exceptions = repos.exceptions.list(month=month)
    approval = repos.approvals.get(month)
    error_cases = repos.error_cases.list(month)

    results = run.results
    if kind == "unresolved":
        results = [r for r in results if r.category in (Category.REVIEW, Category.ERROR, Category.HOLD, Category.AUTOMATABLE)]

    by_plant_rechecks: Dict[str, List[Any]] = {}
    for rc in rechecks:
        by_plant_rechecks.setdefault(rc.plant_id, []).append(rc)

    reverted_ids = {a.reverts for a in adjustments if a.reverts}
    automation_rows = []
    for a in adjustments:
        if a.reverts:
            continue  # 되돌림 행은 원래 행에 '되돌림' 표시로 합쳐 보여준다
        automation_rows.append(
            {
                "plant_id": a.plant_id,
                "kind": a.kind.value,
                "partner_id": a.partner_id,
                "kwh_before": _dec(a.kwh_before),
                "kwh_after": _dec(a.kwh_after),
                "basis": a.basis.value,
                "basis_label": "추정" if a.basis == Basis.ESTIMATED else "실제",
                "formula": a.formula,
                "exception_id": a.exception_id,
                "applied_by": a.applied_by,
                "applied_at": a.applied_at.isoformat() if a.applied_at else None,
                "reverted": a.adjustment_id in reverted_ids,
            }
        )

    recheck_summary = []
    for pid, rcs in sorted(by_plant_rechecks.items()):
        last = rcs[-1]
        recheck_summary.append(
            {
                "plant_id": pid,
                "attempts": len(rcs),
                "passed": last.passed,
                "last_cause": last.cause,
                "last_action": last.recommended_action,
                "evidence": evidence_dict(last.evidence),
            }
        )

    counts = run.by_category()
    effective = [a for a in adjustments if not a.reverts and a.adjustment_id not in reverted_ids]
    facts = {k: str(v) for k, v in counts.items()}
    facts.update(
        {
            "month": month,
            "total": str(len(run.results)),
            "applied": str(len(effective)),
            "estimated": str(sum(1 for a in effective if a.basis == Basis.ESTIMATED)),
            "recheck_failed": str(sum(1 for rcs in by_plant_rechecks.values() if not rcs[-1].passed)),
            "approval": "확정({})".format(approval.actor) if approval else "미확정",
        }
    )
    summary, summary_source = svc.explainer.summarize(facts)

    return {
        "kind": kind,
        "summary": summary,
        "summary_source": summary_source,
        "month": month,
        "generated_from_run": run.run_id,
        "run_at": run.created_at.isoformat(),
        "load_counts": run.counts,
        "category_counts": counts,
        "applied_exception_ids": sorted(
            {a.exception_id for a in adjustments if a.exception_id and not a.reverts and a.adjustment_id not in reverted_ids}
        ),
        "exceptions": [
            {"exception_id": e.exception_id, "plant_id": e.plant_id, "type": e.type.value, "status": e.status.value, "version": e.version}
            for e in exceptions
        ],
        "automation": automation_rows,
        "estimated_count": sum(
            1 for a in adjustments if a.basis == Basis.ESTIMATED and not a.reverts and a.adjustment_id not in reverted_ids
        ),
        "rechecks": recheck_summary,
        "holds": [
            {"plant_id": h.plant_id, "reason": h.reason, "actor": h.actor, "at": h.at.isoformat()}
            for h in holds
            if not h.released
        ],
        "items": [
            {
                "plant_id": r.plant_id,
                "plant_name": r.plant_name,
                "category": r.category.value,
                "journal_amount": _dec(r.journal_amount),
                "invoice_kwh": _dec(r.invoice_kwh),
                "tax_amount": _dec(r.tax_amount),
                "tags": [tag_label(t) for t in r.tags],
                "summary": r.summary,
                "priority": r.priority.value,
            }
            for r in results
            if r.category != Category.PASS
        ],
        "error_cases": [
            {"case_no": c.case_no, "occurred_on": c.occurred_on.isoformat(), "plant_id": c.plant_id, "symptom": c.symptom}
            for c in error_cases
        ],
        "approval": (
            {"actor": approval.actor, "at": approval.at.isoformat(), "open_holds": approval.open_holds, "note": approval.note}
            if approval
            else None
        ),
    }
