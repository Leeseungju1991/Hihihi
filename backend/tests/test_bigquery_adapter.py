"""BigQuery 어댑터 — 실제 BQ 없이 SQL/파라미터/직렬화 계약만 검증 (FakeExecutor)."""
import dataclasses
import datetime as dt
import json
from decimal import Decimal as D

from settlement.adapters.bigquery import Executor, bigquery_repositories, _shift_month
from settlement.adapters.codec import from_dict, to_dict
from settlement.domain.models import Adjustment, Hold, ReconcileRun, RecheckRecord, SettlementException
from settlement.engine.reconcile import reconcile
from settlement.fixtures import MONTH, demo_bundle, demo_exceptions


class FakeExecutor(Executor):
    def __init__(self, views=None):
        self.views = views or {}
        self.inserted = {}
        self.queries = []

    def query(self, sql, params):
        self.queries.append((sql, params))
        for name, rows in self.views.items():
            if "." + name + "`" in sql:
                return rows
        return []

    def insert(self, table, rows):
        json.dumps(rows)  # insert_rows_json 로 보낼 수 있어야 함
        self.inserted.setdefault(table.split(".")[-1], []).extend(rows)


def repos(ex, monkeypatch):
    monkeypatch.setenv("AX_BQ_PROJECT", "proj")
    return bigquery_repositories(ex)


def test_source_load_uses_params_and_decodes(monkeypatch):
    b = demo_bundle()
    views = {
        "v_journal_412": [to_dict(j) for j in b.journals],
        "v_sales_invoice": [{k: v for k, v in to_dict(i).items() if k != "source"} for i in b.invoices],
        "v_tax_invoice": [to_dict(t) for t in b.tax_invoices],
        "v_confirmed_price": [to_dict(p) for p in b.prices],
        "v_meter_cumulative": [to_dict(m) for m in b.meter_readings],
        "v_plant": [to_dict(p) for p in b.plants.values()],
    }
    ex = FakeExecutor(views)
    loaded = repos(ex, monkeypatch).source.load(MONTH)
    assert loaded.journals == b.journals
    assert loaded.tax_invoices == b.tax_invoices
    assert loaded.plants == b.plants
    # 사용자 값은 SQL 문자열이 아니라 파라미터로만 전달
    assert all(MONTH not in sql for sql, _ in ex.queries)
    # 원천은 SELECT 만
    assert all(sql.strip().upper().startswith("SELECT") for sql, _ in ex.queries)
    # 같은 결과로 대조
    assert [r.category for r in reconcile(loaded, demo_exceptions())] == [r.category for r in reconcile(b, demo_exceptions())]


def test_writes_go_only_to_app_dataset(monkeypatch):
    ex = FakeExecutor()
    r = repos(ex, monkeypatch)
    exc = demo_exceptions()[1]
    exc.updated_at = dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)
    r.exceptions.save(exc)
    r.holds.save(Hold(MONTH, "P008", "사유", "a@b", dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)))
    assert set(ex.inserted) == {"exception_versions", "holds"}
    row = ex.inserted["exception_versions"][0]
    assert row["base_date"] == "2026-08-11" and row["type"] == "TRANSFER" and "recorded_at" in row
    assert from_dict(SettlementException, row) == exc


def test_run_snapshot_round_trip(monkeypatch):
    b = demo_bundle()
    run = ReconcileRun("r1", MONTH, dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc), "a@b", b.counts(), reconcile(b, demo_exceptions()))
    ex = FakeExecutor()
    r = repos(ex, monkeypatch)
    r.runs.save(run)
    ex.views["run_snapshots"] = ex.inserted["run_snapshots"]
    back = r.runs.get("r1")
    assert back == run


def test_adjustment_and_recheck_rows(monkeypatch):
    b = demo_bundle()
    res = {x.plant_id: x for x in reconcile(b, demo_exceptions())}
    ex = FakeExecutor()
    r = repos(ex, monkeypatch)
    r.adjustments.add(res["P004"].candidate_adjustments)
    row = ex.inserted["adjustments"][0]
    assert "kwh_delta" not in row and row["basis"] == "ACTUAL"
    assert from_dict(Adjustment, row) == res["P004"].candidate_adjustments[0]

    rec = RecheckRecord(MONTH, "P004", 1, True, res["P004"].category, "", "", res["P004"].evidence, "a", dt.datetime(2026, 9, 1), "MANUAL")
    r.rechecks.add(rec)
    ex.views["rechecks"] = ex.inserted["rechecks"]
    assert r.rechecks.list(MONTH) == [rec]


def test_shift_month():
    assert _shift_month("2026-01", -12) == "2025-01"
    assert _shift_month("2026-01", -1) == "2025-12"
