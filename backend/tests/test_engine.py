import datetime as dt
from decimal import Decimal as D

import pytest

from settlement.config import RuleConfig
from settlement.domain.models import AdjustmentKind, Basis, Category, IssueTag, SettlementException, ExceptionType
from settlement.engine.numbers import percentile
from settlement.engine.reconcile import reconcile
from settlement.fixtures import demo_bundle, demo_exceptions


@pytest.fixture
def results():
    return {r.plant_id: r for r in reconcile(demo_bundle(), demo_exceptions())}


EXPECTED = {
    "P001": Category.PASS,
    "P002": Category.PASS,
    "P003": Category.PASS,
    "P004": Category.AUTOMATABLE,
    "P005": Category.AUTOMATABLE,
    "P006": Category.AUTOMATABLE,
    "P007": Category.PASS,
    "P008": Category.REVIEW,
    "P009": Category.REVIEW,
    "P010": Category.REVIEW,
    "P011": Category.ERROR,
    "P012": Category.AUTOMATABLE,
}


def test_classification_matches_scenarios(results):
    assert {k: v.category for k, v in results.items()} == EXPECTED


def test_known_anomalies_are_never_missed(results):
    """오탐/미탐 기준: 알려진 이상 건이 모두 해당 태그로 잡힌다."""
    assert IssueTag.METER_SHORTAGE in results["P004"].tags
    assert IssueTag.PARTNER_MISMATCH in results["P006"].tags
    assert IssueTag.INVALID_TAX_INVOICE in results["P008"].tags
    assert IssueTag.DOUBLE_COUNT in results["P009"].tags
    assert IssueTag.HOURS_EXCEEDED in results["P010"].tags


def test_disabled_tax_invoices_are_excluded(results):
    assert results["P007"].tax_amount == results["P007"].journal_amount


def test_manual_issue_combines_invoice(results):
    adj = results["P005"].candidate_adjustments
    assert len(adj) == 1 and adj[0].kind == AdjustmentKind.MANUAL_INVOICE
    assert adj[0].kwh_after - adj[0].kwh_before == D("2850")
    assert adj[0].exception_id == "EX-0001"


def test_transfer_prorates_by_day(results):
    adj = {a.partner_id: a for a in results["P006"].candidate_adjustments}
    # 8/11 기준 → 10일/31일 = 3,500, 21일 = 7,350
    assert adj["C-SOLAR1"].kwh_after == D("3500")
    assert adj["C-SOLAR2"].kwh_after == D("7350")
    assert all(a.kind == AdjustmentKind.PRORATION for a in adj.values())


def test_meter_correction_actual_from_cumulative(results):
    (adj,) = results["P004"].candidate_adjustments
    assert adj.basis == Basis.ACTUAL
    assert adj.kwh_after == D("10850")


def test_meter_correction_estimated_from_peers(results):
    (adj,) = results["P012"].candidate_adjustments
    assert adj.basis == Basis.ESTIMATED
    assert "[추정]" in adj.formula


def test_amounts_are_never_adjusted(results):
    """보정은 kWh 만 바꾼다 — 분개·세금계산서 금액은 원천 그대로."""
    b = demo_bundle()
    for pid, r in results.items():
        assert r.journal_amount == sum((j.amount for j in b.journals if j.plant_id == pid), D(0))


def test_smp_tolerance_boundary():
    b = demo_bundle()
    # P001 분개를 kWh 당 0.5원 만큼 올림 → 허용, 0.51원 → 미결
    ok = D("10850") * D("0.5")
    b.journals = [j if j.plant_id != "P001" else j.__class__(j.entry_id, j.plant_id, j.month, j.partner_id, j.amount + ok) for j in b.journals]
    b.tax_invoices = [t if t.plant_id != "P001" else t.__class__(t.nts_id, t.plant_id, t.month, t.partner_id, t.supply_amount + ok, t.status) for t in b.tax_invoices]
    r = {x.plant_id: x for x in reconcile(b)}["P001"]
    assert r.category == Category.PASS

    b2 = demo_bundle()
    over = D("10850") * D("0.51")
    b2.journals = [j if j.plant_id != "P001" else j.__class__(j.entry_id, j.plant_id, j.month, j.partner_id, j.amount + over) for j in b2.journals]
    b2.tax_invoices = [t if t.plant_id != "P001" else t.__class__(t.nts_id, t.plant_id, t.month, t.partner_id, t.supply_amount + over, t.status) for t in b2.tax_invoices]
    r2 = {x.plant_id: x for x in reconcile(b2)}["P001"]
    assert IssueTag.METER_SHORTAGE in r2.tags


def test_hours_cap_uses_percentile_when_population_large():
    b = demo_bundle()
    b.hours_population = [D(i) / D(10) for i in range(10, 110)]  # 1.0 ~ 10.9h, 100개
    cfg = RuleConfig()
    cap = percentile(b.hours_population, cfg.hours_percentile)
    assert cap is not None and D("10.7") < cap < D("10.9")
    r = {x.plant_id: x for x in reconcile(b, cfg=cfg)}
    assert IssueTag.HOURS_EXCEEDED in r["P010"].tags  # 11.67h


def test_closed_exception_is_ignored():
    excs = demo_exceptions()
    from settlement.domain.models import ExceptionStatus

    excs[0].status = ExceptionStatus.CLOSED
    r = {x.plant_id: x for x in reconcile(demo_bundle(), excs)}
    assert not any(a.kind == AdjustmentKind.MANUAL_INVOICE for a in r["P005"].candidate_adjustments)


def test_other_exception_has_no_effect():
    exc = SettlementException("EX-9", "2026-08", "P008", ExceptionType.OTHER, note="메모")
    r = {x.plant_id: x for x in reconcile(demo_bundle(), [exc])}
    assert r["P008"].category == Category.REVIEW
