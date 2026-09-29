"""발전소 단위 원장 — 원천 행을 발전소별로 모으고, 보정값을 겹쳐 '유효 검침량'을 만든다.

금액(분개·세금계산서·송장 금액)은 원천 그대로 두고, 보정은 검침량(kWh)에만 적용한다.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

from ..domain.models import (
    Adjustment,
    ConfirmedPrice,
    JournalEntry,
    Plant,
    SalesInvoice,
    SourceBundle,
    TaxInvoice,
    TaxInvoiceStatus,
)

ZERO = Decimal("0")


@dataclass
class PlantLedger:
    plant_id: str
    month: str
    plant: Optional[Plant]
    journals: List[JournalEntry] = field(default_factory=list)
    invoices: List[SalesInvoice] = field(default_factory=list)
    tax_invoices: List[TaxInvoice] = field(default_factory=list)
    price: Optional[Decimal] = None
    adjustments: List[Adjustment] = field(default_factory=list)

    # ── 분개 ──
    @property
    def journal_total(self) -> Decimal:
        return sum((j.amount for j in self.journals), ZERO)

    def journal_by_partner(self) -> Dict[str, Decimal]:
        out: Dict[str, Decimal] = OrderedDict()
        for j in self.journals:
            out[j.partner_id] = out.get(j.partner_id, ZERO) + j.amount
        return out

    # ── 세금계산서 (2단계: 무효 제외) ──
    @property
    def valid_tax(self) -> List[TaxInvoice]:
        return [t for t in self.tax_invoices if t.status == TaxInvoiceStatus.VALID]

    @property
    def disabled_tax(self) -> List[TaxInvoice]:
        return [t for t in self.tax_invoices if t.status == TaxInvoiceStatus.DISABLE]

    @property
    def tax_total(self) -> Decimal:
        return sum((t.supply_amount for t in self.valid_tax), ZERO)

    def tax_by_partner(self) -> Dict[str, Decimal]:
        out: Dict[str, Decimal] = OrderedDict()
        for t in self.valid_tax:
            out[t.partner_id] = out.get(t.partner_id, ZERO) + t.supply_amount
        return out

    # ── 송장 검침량 (+보정) ──
    def raw_kwh_by_partner(self) -> Dict[str, Decimal]:
        out: Dict[str, Decimal] = OrderedDict()
        for inv in self.invoices:
            out[inv.partner_id] = out.get(inv.partner_id, ZERO) + inv.meter_kwh
        return out

    def kwh_by_partner(self, extra: Optional[List[Adjustment]] = None) -> Dict[str, Decimal]:
        out = self.raw_kwh_by_partner()
        for adj in list(self.adjustments) + list(extra or []):
            out[adj.partner_id] = out.get(adj.partner_id, ZERO) + adj.kwh_delta
        return out

    def kwh_total(self, extra: Optional[List[Adjustment]] = None) -> Decimal:
        return sum(self.kwh_by_partner(extra).values(), ZERO)

    def main_partner(self) -> str:
        """분개 금액이 가장 큰 조합. 보정 kWh 를 귀속시킬 때 사용."""
        by = self.journal_by_partner()
        if by:
            return max(by.items(), key=lambda kv: kv[1])[0]
        kwh = self.raw_kwh_by_partner()
        if kwh:
            return max(kwh.items(), key=lambda kv: kv[1])[0]
        return self.plant.partner_id if self.plant else ""


def resolve_price(prices: List[ConfirmedPrice], month: str, plant_id: str) -> Optional[Decimal]:
    specific = [p for p in prices if p.month == month and p.plant_id == plant_id]
    if specific:
        return specific[-1].unit_price
    common = [p for p in prices if p.month == month and not p.plant_id]
    return common[-1].unit_price if common else None


def build_ledgers(bundle: SourceBundle, committed: List[Adjustment]) -> "OrderedDict[str, PlantLedger]":
    ledgers: "OrderedDict[str, PlantLedger]" = OrderedDict()

    def get(pid: str) -> PlantLedger:
        if pid not in ledgers:
            ledgers[pid] = PlantLedger(
                plant_id=pid,
                month=bundle.month,
                plant=bundle.plants.get(pid),
                price=resolve_price(bundle.prices, bundle.month, pid),
            )
        return ledgers[pid]

    for j in bundle.journals:
        if j.month == bundle.month:
            get(j.plant_id).journals.append(j)
    for inv in bundle.invoices:
        if inv.month == bundle.month:
            get(inv.plant_id).invoices.append(inv)
    for t in bundle.tax_invoices:
        if t.month == bundle.month:
            get(t.plant_id).tax_invoices.append(t)
    for adj in effective_adjustments(committed):
        if adj.month == bundle.month and adj.plant_id in ledgers:
            ledgers[adj.plant_id].adjustments.append(adj)
    return ledgers


def effective_adjustments(committed: List[Adjustment]) -> List[Adjustment]:
    """되돌림 행과, 되돌려진 원래 행을 모두 뺀 유효 보정."""
    reverted = {a.reverts for a in committed if a.reverts}
    return [a for a in committed if not a.reverts and a.adjustment_id not in reverted]
