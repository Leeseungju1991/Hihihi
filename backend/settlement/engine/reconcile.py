"""3자 대조 파이프라인.

1단계   분개(412) 로드 → 발전소별 원장
1.5단계 예외 반영 (보정 후보: 수기 송장 결합 / 일할 안분)
2단계   세금계산서 교차 검증 (무효 제외)
3단계   확정 단가 역산 검산 (분개 ÷ 검침량, 허용 편차 초과 시 미결)
4단계   이중계상 / 일 발전시간 퍼센타일 상한
보정    누락 검침량 (누적값 차이 → 실제, 인근 발전소 → 추정)
분류    통과 / 자동화 대상 / 확인 대상 / 보류 / 에러

순수 함수: 입력(원천 묶음·예외·확정 보정·보류)만으로 결과가 결정된다. I/O 없음.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Set

from ..config import RuleConfig
from ..domain.models import (
    Adjustment,
    Category,
    Evidence,
    Hold,
    IssueTag,
    PlantResult,
    Priority,
    SettlementException,
    SourceBundle,
)
from .adjustments import (
    manual_invoice_candidates,
    meter_correction_candidate,
    proration_candidates,
)
from .ledger import PlantLedger, build_ledgers
from .numbers import HOURS, PRICE, WON, days_in_month, fmt_kwh, fmt_price, fmt_won, percentile, q

ZERO = Decimal("0")

TAG_LABELS = {
    IssueTag.METER_SHORTAGE: "검침 부족",
    IssueTag.DOUBLE_COUNT: "이중계상 의심",
    IssueTag.PARTNER_MISMATCH: "조합 불일치",
    IssueTag.HOURS_EXCEEDED: "발전시간 초과",
    IssueTag.INVALID_TAX_INVOICE: "무효 계산서",
}


@dataclass
class Evaluation:
    kwh_total: Decimal
    invoice_amount: Decimal
    implied_price: Optional[Decimal]
    implied_kwh: Optional[Decimal]
    daily_hours: Optional[Decimal]
    tags: List[IssueTag] = field(default_factory=list)
    messages: List[str] = field(default_factory=list)
    evidence: List[Evidence] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and not self.tags

    def tag(self, t: IssueTag, message: str) -> None:
        if t not in self.tags:
            self.tags.append(t)
        self.messages.append(message)


def hours_cap(values: Iterable[Decimal], cfg: RuleConfig) -> Decimal:
    data = [v for v in values if v is not None and v > ZERO]
    if len(data) < cfg.hours_min_population:
        return cfg.hours_hard_cap
    p = percentile(data, cfg.hours_percentile)
    return p if p is not None else cfg.hours_hard_cap


def _daily_hours(ledger: PlantLedger, kwh: Decimal) -> Optional[Decimal]:
    if ledger.plant is None or ledger.plant.capacity_kw <= ZERO:
        return None
    return q(kwh / ledger.plant.capacity_kw / Decimal(days_in_month(ledger.month)), HOURS)


def evaluate(
    ledger: PlantLedger,
    cfg: RuleConfig,
    cap: Decimal,
    extra: Optional[List[Adjustment]] = None,
) -> Evaluation:
    kwh_by_partner = ledger.kwh_by_partner(extra)
    kwh_total = sum(kwh_by_partner.values(), ZERO)
    J = ledger.journal_total
    T = ledger.tax_total
    price = ledger.price

    ev = Evaluation(
        kwh_total=kwh_total,
        invoice_amount=q(kwh_total * price, WON) if price is not None else ZERO,
        implied_price=q(J / kwh_total, PRICE) if kwh_total > ZERO else None,
        implied_kwh=(J / price) if price else None,
        daily_hours=_daily_hours(ledger, kwh_total),
    )
    ev.evidence += [
        Evidence("journal_amount", "분개(412)", fmt_won(J)),
        Evidence("invoice_kwh", "송장 검침량", fmt_kwh(kwh_total)),
        Evidence("tax_amount", "세금계산서(유효)", fmt_won(T)),
    ]

    # ── 에러: 원천 없음 ──
    if ledger.plant is None:
        ev.error = "발전소 마스터에 없는 발전소"
        return ev
    if not ledger.journals:
        ev.error = "분개(412) 없음"
        return ev
    if not ledger.invoices and not ledger.tax_invoices and not extra and not ledger.adjustments:
        ev.error = "송장·세금계산서 모두 없음"
        return ev
    if price is None or price <= ZERO:
        ev.error = "확정 단가 없음"
        return ev

    ev.evidence.append(Evidence("unit_price", "확정 단가", fmt_price(price)))

    # ── 2단계: 세금계산서 교차 검증 (무효 제외) ──
    negative_valid = [t for t in ledger.valid_tax if t.supply_amount < ZERO]
    if negative_valid:
        ev.tag(
            IssueTag.INVALID_TAX_INVOICE,
            "유효 상태의 음수 세금계산서 {}건 (무효 처리 여부 확인)".format(len(negative_valid)),
        )
        ev.evidence.append(
            Evidence("negative_tax", "음수 세금계산서", ", ".join(fmt_won(t.supply_amount) for t in negative_valid))
        )
    if ledger.disabled_tax and T == ZERO and J != ZERO:
        ev.tag(IssueTag.INVALID_TAX_INVOICE, "유효 세금계산서가 없음 — 정상 계산서가 무효로 분류됐을 가능성")
        ev.evidence.append(
            Evidence("disabled_tax", "무효 세금계산서", ", ".join(fmt_won(t.supply_amount) for t in ledger.disabled_tax))
        )

    tax_diff = T - J
    if abs(tax_diff) > cfg.amount_tolerance and IssueTag.INVALID_TAX_INVOICE not in ev.tags:
        ev.tag(IssueTag.PARTNER_MISMATCH, "세금계산서가 분개 대비 {}".format(fmt_won(tax_diff)))
        ev.evidence.append(Evidence("tax_diff", "세금계산서−분개", fmt_won(tax_diff)))

    # 조합별 세금계산서 ↔ 분개
    jb, tb = ledger.journal_by_partner(), ledger.tax_by_partner()
    if abs(tax_diff) <= cfg.amount_tolerance and len(set(jb) | set(tb)) > 1:
        for partner in sorted(set(jb) | set(tb)):
            d = tb.get(partner, ZERO) - jb.get(partner, ZERO)
            if abs(d) > cfg.amount_tolerance:
                ev.tag(IssueTag.PARTNER_MISMATCH, "조합 {} 세금계산서−분개 {}".format(partner, fmt_won(d)))
                ev.evidence.append(Evidence("tax_diff_" + partner, "조합 {} 세금계산서−분개".format(partner), fmt_won(d)))

    # ── 3단계: 확정 단가 역산 검산 ──
    if kwh_total <= ZERO:
        ev.tag(IssueTag.METER_SHORTAGE, "송장 검침량 0kWh")
    else:
        dev = ev.implied_price - price  # type: ignore[operator]
        ev.evidence.append(Evidence("implied_price", "역산 단가(분개÷검침량)", fmt_price(ev.implied_price)))  # type: ignore[arg-type]
        if abs(dev) > cfg.smp_tolerance:
            implied_kwh = ev.implied_kwh or ZERO
            gap = kwh_total - implied_kwh
            ratio = (gap / implied_kwh * Decimal("100")) if implied_kwh else ZERO
            ev.evidence.append(Evidence("implied_kwh", "역산 검침량(분개÷단가)", fmt_kwh(implied_kwh)))
            ev.evidence.append(Evidence("kwh_gap_pct", "역산 대비 검침량 차이율", "{}%".format(q(ratio, Decimal("0.1")))))
            if gap < ZERO:
                ev.tag(
                    IssueTag.METER_SHORTAGE,
                    "송장 검침량이 단가 역산 대비 {}% 부족 ({})".format(q(-ratio, Decimal("0.1")), fmt_kwh(-gap)),
                )
            else:
                ev.tag(
                    IssueTag.DOUBLE_COUNT,
                    "송장 검침량이 단가 역산 대비 {}% 초과 ({})".format(q(ratio, Decimal("0.1")), fmt_kwh(gap)),
                )

        # 조합별 검산 (조합이 둘 이상일 때)
        if len(set(jb) | set(kwh_by_partner)) > 1:
            for partner in sorted(set(jb) | set(kwh_by_partner)):
                pk = kwh_by_partner.get(partner, ZERO)
                pj = jb.get(partner, ZERO)
                if pk <= ZERO and pj == ZERO:
                    continue
                pdev = (pj / pk - price) if pk > ZERO else None
                if pdev is None or abs(pdev) > cfg.smp_tolerance:
                    ev.tag(
                        IssueTag.PARTNER_MISMATCH,
                        "조합 {} 검침량 {} × 단가 ≠ 분개 {}".format(partner, fmt_kwh(pk), fmt_won(pj)),
                    )
                    ev.evidence.append(
                        Evidence("partner_" + partner, "조합 {} 검침량/분개".format(partner), "{} / {}".format(fmt_kwh(pk), fmt_won(pj)))
                    )

    # ── 4단계: 이중계상 ──
    dup_inv = [k for k, n in Counter((i.partner_id, i.meter_kwh, i.amount) for i in ledger.invoices).items() if n > 1]
    dup_tax = [k for k, n in Counter((t.partner_id, t.supply_amount) for t in ledger.valid_tax).items() if n > 1]
    dup_jnl = [k for k, n in Counter((j.partner_id, j.amount) for j in ledger.journals).items() if n > 1]
    for label, dups in (("송장", dup_inv), ("세금계산서", dup_tax), ("분개", dup_jnl)):
        if dups:
            ev.tag(IssueTag.DOUBLE_COUNT, "동일 {} {}건 중복".format(label, len(dups)))
            ev.evidence.append(Evidence("dup_" + label, "중복 " + label, str(len(dups)) + "건"))

    # ── 4단계: 일 발전시간 상한 ──
    if ev.daily_hours is not None:
        ev.evidence.append(Evidence("daily_hours", "일 평균 발전시간", "{}h".format(ev.daily_hours)))
        if ev.daily_hours > cap:
            ev.tag(
                IssueTag.HOURS_EXCEEDED,
                "일 평균 발전시간 {}h 가 상한 {}h 초과".format(ev.daily_hours, q(cap, HOURS)),
            )
            ev.evidence.append(Evidence("hours_cap", "발전시간 상한", "{}h".format(q(cap, HOURS))))
    return ev


def _priority(ev: Evaluation, ledger: PlantLedger, cfg: RuleConfig) -> Priority:
    diffs = [abs(ledger.tax_total - ledger.journal_total)]
    if ev.implied_kwh is not None and ledger.price:
        diffs.append(abs(ev.kwh_total - ev.implied_kwh) * ledger.price)
    worst = max(diffs)
    if worst >= cfg.priority_high:
        return Priority.HIGH
    if worst >= cfg.priority_medium:
        return Priority.MEDIUM
    return Priority.LOW


def _peer_yields(ledgers: Dict[str, PlantLedger], evals: Dict[str, Evaluation]) -> Dict[str, Dict[str, Decimal]]:
    """지역별 정상(통과) 발전소 비발전량(kWh/kW). 추정 보정의 기준."""
    by_region: Dict[str, Dict[str, Decimal]] = {}
    for pid, ev in evals.items():
        led = ledgers[pid]
        if not ev.ok or led.plant is None or led.plant.capacity_kw <= ZERO:
            continue
        by_region.setdefault(led.plant.region, {})[pid] = ev.kwh_total / led.plant.capacity_kw
    return by_region


MIN_PEERS = 3


def reconcile(
    bundle: SourceBundle,
    exceptions: Sequence[SettlementException] = (),
    committed: Sequence[Adjustment] = (),
    holds: Sequence[Hold] = (),
    cfg: Optional[RuleConfig] = None,
    only: Optional[Set[str]] = None,
    failed_signatures: Optional[Dict[str, Set[str]]] = None,
) -> List[PlantResult]:
    """failed_signatures: 발전소별로 이미 자동화했다가 재검증 미통과된 보정 묶음 서명.
    같은 보정만 다시 제안되면 자동화 대상이 아니라 확인 대상으로 분류한다(무한 반복 방지)."""
    cfg = cfg or RuleConfig()
    failed_signatures = failed_signatures or {}
    ledgers = build_ledgers(bundle, list(committed))

    # 발전시간 상한: 과거 모집단이 있으면 그것, 없으면 당월 전체(원천 검침량 기준)
    population = bundle.hours_population or [
        h for h in (_daily_hours(l, l.kwh_total()) for l in ledgers.values()) if h is not None
    ]
    cap = hours_cap(population, cfg)

    base: Dict[str, Evaluation] = {pid: evaluate(l, cfg, cap) for pid, l in ledgers.items()}
    peers = _peer_yields(ledgers, base)
    active_holds = {h.plant_id: h for h in holds if h.month == bundle.month and not h.released}

    results: List[PlantResult] = []
    for pid, led in ledgers.items():
        if only is not None and pid not in only:
            continue
        ev = base[pid]

        candidates: List[Adjustment] = []
        if not ev.error:
            candidates += manual_invoice_candidates(led, exceptions)
            candidates += proration_candidates(led, exceptions, candidates)
            after = evaluate(led, cfg, cap, candidates) if candidates else ev
            if IssueTag.METER_SHORTAGE in after.tags:
                region = led.plant.region if led.plant else ""
                region_peers = {k: v for k, v in peers.get(region, {}).items() if k != pid}
                if len(region_peers) < MIN_PEERS:
                    region_peers = {}
                mc = meter_correction_candidate(led, candidates, bundle.meter_readings, region_peers)
                if mc is not None:
                    candidates.append(mc)

        # 통과가 최우선(보류 중이던 건도 재검증으로 해소되면 통과), 그다음 보류가 에러·미결을 덮는다.
        if ev.ok:
            category = Category.PASS
        elif pid in active_holds:
            category = Category.HOLD
        elif ev.error:
            category = Category.ERROR
        elif candidates and signature(candidates) not in failed_signatures.get(pid, set()):
            category = Category.AUTOMATABLE
        else:
            category = Category.REVIEW
        retried = bool(candidates) and category == Category.REVIEW and signature(candidates) in failed_signatures.get(pid, set())

        exc_ids = sorted({a.exception_id for a in led.adjustments if a.exception_id})
        summary = ev.error or (ev.messages[0] if ev.messages else "")
        if category == Category.HOLD:
            summary = "[보류] {} — {}".format(active_holds[pid].reason, summary)
        elif retried:
            summary = "자동화 후 재검증 미통과 — " + summary

        results.append(
            PlantResult(
                plant_id=pid,
                plant_name=led.plant.name if led.plant else pid,
                month=bundle.month,
                category=category,
                journal_amount=led.journal_total,
                invoice_kwh=ev.kwh_total,
                invoice_amount=ev.invoice_amount,
                tax_amount=led.tax_total,
                unit_price=led.price,
                implied_price=ev.implied_price,
                implied_kwh=q(ev.implied_kwh, Decimal("0.001")) if ev.implied_kwh is not None else None,
                daily_hours=ev.daily_hours,
                tags=list(ev.tags),
                summary=summary,
                priority=_priority(ev, led, cfg) if not ev.error else Priority.HIGH,
                evidence=list(ev.evidence),
                applied_exception_ids=exc_ids,
                applied_adjustment_ids=[a.adjustment_id for a in led.adjustments],
                candidate_adjustments=candidates,
                error=ev.error,
            )
        )
    return results


def signature(candidates: Sequence[Adjustment]) -> str:
    """보정 묶음의 내용 서명 (ID·시각 제외)."""
    parts = sorted(
        "{}|{}|{}|{}|{}".format(a.kind.value, a.partner_id, a.kwh_after, a.basis.value, a.exception_id) for a in candidates
    )
    return ";".join(parts)


def simulate(result: PlantResult, bundle: SourceBundle, committed: Sequence[Adjustment], cfg: Optional[RuleConfig] = None) -> Evaluation:
    """자동화 미리보기 — 후보 보정을 적용했다고 가정한 평가 (저장하지 않음)."""
    cfg = cfg or RuleConfig()
    ledgers = build_ledgers(bundle, list(committed))
    led = ledgers[result.plant_id]
    population = bundle.hours_population or [
        h for h in (_daily_hours(l, l.kwh_total()) for l in ledgers.values()) if h is not None
    ]
    return evaluate(led, cfg, hours_cap(population, cfg), list(result.candidate_adjustments))


def tag_label(tag: IssueTag) -> str:
    return TAG_LABELS[tag]
