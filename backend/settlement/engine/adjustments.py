"""보정 후보 산출.

1.5단계 예외 반영 — 수기 송장 결합, 양수도·거래처 변경·PPA 지연 일할 안분
보정 — 누락 검침량: 검침 누적값 차이(실제) → 없으면 인근 발전소 비발전량(추정)

모두 '후보'만 만들고 저장하지 않는다. 저장(보정 테이블 기록)은 워크플로의 자동화 실행에서만 한다.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from ..domain.models import (
    Adjustment,
    AdjustmentKind,
    Basis,
    ExceptionStatus,
    ExceptionType,
    MeterReading,
    SettlementException,
    SPLIT_EXCEPTION_TYPES,
)
from .ledger import PlantLedger
from .numbers import KWH, days_in_month, fmt_kwh, median, month_start, next_month_start, q

ZERO = Decimal("0")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def _open_exceptions(exceptions: Sequence[SettlementException], ledger: PlantLedger) -> List[SettlementException]:
    return [
        e
        for e in exceptions
        if e.plant_id == ledger.plant_id
        and e.month == ledger.month
        and e.status != ExceptionStatus.CLOSED
    ]


def _already_applied(ledger: PlantLedger, exception_id: str) -> bool:
    return any(a.exception_id == exception_id for a in ledger.adjustments)


def manual_invoice_candidates(
    ledger: PlantLedger, exceptions: Sequence[SettlementException]
) -> List[Adjustment]:
    out: List[Adjustment] = []
    for e in _open_exceptions(exceptions, ledger):
        if e.type != ExceptionType.MANUAL_ISSUE or e.manual_kwh is None:
            continue
        if _already_applied(ledger, e.exception_id):
            continue
        before = ledger.kwh_by_partner(out).get(e.partner_after, ZERO)
        out.append(
            Adjustment(
                adjustment_id=_new_id(),
                month=ledger.month,
                plant_id=ledger.plant_id,
                kind=AdjustmentKind.MANUAL_INVOICE,
                partner_id=e.partner_after,
                kwh_before=before,
                kwh_after=before + e.manual_kwh,
                basis=Basis.ACTUAL,
                formula="시스템 송장 {} + 수기 발행 {} (예외 {})".format(
                    fmt_kwh(before), fmt_kwh(e.manual_kwh), e.exception_id
                ),
                exception_id=e.exception_id,
            )
        )
    return out


def proration_candidates(
    ledger: PlantLedger,
    exceptions: Sequence[SettlementException],
    prior: List[Adjustment],
) -> List[Adjustment]:
    """기준일 전날까지 = 변경 전 조합, 기준일부터 = 변경 후 조합 으로 월 발전량을 일할 안분."""
    out: List[Adjustment] = []
    dim = days_in_month(ledger.month)
    for e in _open_exceptions(exceptions, ledger):
        if e.type not in SPLIT_EXCEPTION_TYPES or e.base_date is None:
            continue
        if _already_applied(ledger, e.exception_id):
            continue
        current = ledger.kwh_by_partner(prior + out)
        pair_total = current.get(e.partner_before, ZERO) + current.get(e.partner_after, ZERO)
        days_before = e.base_date.day - 1
        days_after = dim - days_before
        target_before = q(pair_total * Decimal(days_before) / Decimal(dim), KWH)
        target_after = pair_total - target_before
        formula = "{} × {}일/{}일 → 변경 전 {}, 나머지 {}일 → 변경 후 {} (예외 {})".format(
            fmt_kwh(pair_total),
            days_before,
            dim,
            e.partner_before,
            days_after,
            e.partner_after,
            e.exception_id,
        )
        for partner, target in ((e.partner_before, target_before), (e.partner_after, target_after)):
            before = current.get(partner, ZERO)
            if before == target:
                continue
            out.append(
                Adjustment(
                    adjustment_id=_new_id(),
                    month=ledger.month,
                    plant_id=ledger.plant_id,
                    kind=AdjustmentKind.PRORATION,
                    partner_id=partner,
                    kwh_before=before,
                    kwh_after=target,
                    basis=Basis.ACTUAL,
                    formula=formula,
                    exception_id=e.exception_id,
                )
            )
    return out


def measured_month_kwh(readings: Sequence[MeterReading], plant_id: str, month: str) -> Optional[tuple]:
    """월초·익월초 누적값 차이. (kwh, 시작일, 종료일) 또는 None."""
    start, end = month_start(month), next_month_start(month)
    rs = [r for r in readings if r.plant_id == plant_id]
    at_start = [r for r in rs if r.date <= start]
    at_end = [r for r in rs if r.date >= end]
    if not at_start or not at_end:
        return None
    s = max(at_start, key=lambda r: r.date)
    e = min(at_end, key=lambda r: r.date)
    # 시작/종료 스냅샷이 월 경계에서 너무 멀면 신뢰 불가
    if (start - s.date).days > 1 or (e.date - end).days > 1:
        return None
    diff = e.cumulative_kwh - s.cumulative_kwh
    if diff < ZERO:  # 계량기 리셋 등
        return None
    return diff, s.date, e.date


def meter_correction_candidate(
    ledger: PlantLedger,
    prior: List[Adjustment],
    readings: Sequence[MeterReading],
    peer_yields: Dict[str, Decimal],
) -> Optional[Adjustment]:
    """검침 부족 시 보정안. 누적값 차이(실제)가 우선, 없으면 인근 발전소 비발전량 중앙값(추정)."""
    current_total = ledger.kwh_total(prior)
    partner = ledger.main_partner()
    before = ledger.kwh_by_partner(prior).get(partner, ZERO)

    measured = measured_month_kwh(readings, ledger.plant_id, ledger.month)
    if measured is not None:
        kwh, s_date, e_date = measured
        if kwh <= current_total:
            return None
        return Adjustment(
            adjustment_id=_new_id(),
            month=ledger.month,
            plant_id=ledger.plant_id,
            kind=AdjustmentKind.METER_CORRECTION,
            partner_id=partner,
            kwh_before=before,
            kwh_after=before + (kwh - current_total),
            basis=Basis.ACTUAL,
            formula="누적({}) − 누적({}) = {} (송장 {} 대비 +{})".format(
                e_date, s_date, fmt_kwh(kwh), fmt_kwh(current_total), fmt_kwh(kwh - current_total)
            ),
        )

    if ledger.plant is None or not peer_yields:
        return None
    yield_med = median(peer_yields.values())
    if yield_med is None:
        return None
    est = q(yield_med * ledger.plant.capacity_kw, KWH)
    if est <= current_total:
        return None
    return Adjustment(
        adjustment_id=_new_id(),
        month=ledger.month,
        plant_id=ledger.plant_id,
        kind=AdjustmentKind.METER_CORRECTION,
        partner_id=partner,
        kwh_before=before,
        kwh_after=before + (est - current_total),
        basis=Basis.ESTIMATED,
        formula="인근 {}개소 비발전량 중앙값 {}kWh/kW × 설비 {}kW = {} [추정]".format(
            len(peer_yields), q(yield_med, Decimal("0.01")), ledger.plant.capacity_kw, fmt_kwh(est)
        ),
    )
