"""[미검증 · 회사 연결 예정] BigQuery(프리즘) 구현 — 기능만 구현, 실제 BigQuery 실행 검증 안 함. UNVERIFIED.md §1

BigQuery 구현 (회사 환경).

- 원천: `{project}.{AX_BQ_SRC_DATASET}` 의 정규화 뷰(dataform/definitions/sources)만 SELECT. 쓰기 코드 없음.
- 결과: `{project}.{AX_BQ_APP_DATASET}` 의 append-only 테이블(backend/sql/ddl)에 insert 만 한다.
  UPDATE/DELETE 를 쓰지 않으므로 streaming insert 직후에도 안전하고, 모든 변경이 곧 이력이 된다.

env
  AX_BQ_PROJECT        GCP 프로젝트
  AX_BQ_SRC_DATASET    정규화 원천 뷰 데이터셋 (기본 ax_settlement_src)
  AX_BQ_APP_DATASET    결과 데이터셋 (기본 ax_settlement)
  AX_BQ_LOCATION       기본 asia-northeast3
"""
from __future__ import annotations

import datetime as dt
import json
import os
from decimal import Decimal
from typing import Any, Dict, List, Optional

from ..domain.models import (
    Adjustment,
    Approval,
    ConfirmedPrice,
    ErrorCase,
    Hold,
    JournalEntry,
    MeterReading,
    Plant,
    ReconcileRun,
    RecheckRecord,
    SalesInvoice,
    SettlementException,
    SourceBundle,
    TaxInvoice,
)
from ..engine.numbers import month_start, next_month_start
from ..ports import Repositories
from .codec import from_dict, to_dict


# ─────────────────────────────── 실행기 ───────────────────────────────


class Executor:
    """BigQuery 호출을 한 곳에 모은다. 테스트는 FakeExecutor 로 대체."""

    def query(self, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError

    def insert(self, table: str, rows: List[Dict[str, Any]]) -> None:  # pragma: no cover
        raise NotImplementedError


class BigQueryExecutor(Executor):  # pragma: no cover - 외부 연동
    def __init__(self, project: str, location: str):
        from google.cloud import bigquery  # type: ignore

        self._bq = bigquery
        self._client = bigquery.Client(project=project, location=location)

    def _param(self, name: str, value: Any):
        bq = self._bq
        if isinstance(value, bool):
            t = "BOOL"
        elif isinstance(value, int):
            t = "INT64"
        elif isinstance(value, Decimal):
            t = "NUMERIC"
        elif isinstance(value, dt.datetime):
            t = "TIMESTAMP"
        elif isinstance(value, dt.date):
            t = "DATE"
        else:
            t = "STRING"
        return bq.ScalarQueryParameter(name, t, value)

    def query(self, sql: str, params: Dict[str, Any]) -> List[Dict[str, Any]]:
        cfg = self._bq.QueryJobConfig(query_parameters=[self._param(k, v) for k, v in params.items()])
        return [dict(row.items()) for row in self._client.query(sql, job_config=cfg).result()]

    def insert(self, table: str, rows: List[Dict[str, Any]]) -> None:
        if not rows:
            return
        errors = self._client.insert_rows_json(table, rows)
        if errors:
            raise RuntimeError("BigQuery insert 실패: {}".format(errors))


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class _Base:
    def __init__(self, ex: Executor, project: str, src: str, app: str):
        self.ex = ex
        self.project = project
        self.src = src
        self.app = app

    def s(self, view: str) -> str:
        return "`{}.{}.{}`".format(self.project, self.src, view)

    def t(self, table: str) -> str:
        return "`{}.{}.{}`".format(self.project, self.app, table)

    def table_id(self, table: str) -> str:
        return "{}.{}.{}".format(self.project, self.app, table)


# ─────────────────────────────── 원천 (읽기 전용) ───────────────────────────────


class BigQuerySource(_Base):
    def plants(self) -> Dict[str, Plant]:
        rows = self.ex.query("SELECT plant_id, name, capacity_kw, region, partner_id FROM {}".format(self.s("v_plant")), {})
        return {r["plant_id"]: from_dict(Plant, r) for r in rows}

    def load(self, month: str) -> SourceBundle:
        p = {"month": month}
        journals = [
            from_dict(JournalEntry, r)
            for r in self.ex.query(
                "SELECT entry_id, plant_id, month, partner_id, amount FROM {} WHERE month = @month".format(self.s("v_journal_412")), p
            )
        ]
        invoices = [
            from_dict(SalesInvoice, r)
            for r in self.ex.query(
                "SELECT invoice_id, plant_id, month, partner_id, meter_kwh, amount FROM {} WHERE month = @month".format(
                    self.s("v_sales_invoice")
                ),
                p,
            )
        ]
        taxes = [
            from_dict(TaxInvoice, r)
            for r in self.ex.query(
                "SELECT nts_id, plant_id, month, partner_id, supply_amount, status, issue_date FROM {} WHERE month = @month".format(
                    self.s("v_tax_invoice")
                ),
                p,
            )
        ]
        prices = [
            from_dict(ConfirmedPrice, r)
            for r in self.ex.query(
                "SELECT month, IFNULL(plant_id, '') AS plant_id, unit_price FROM {} WHERE month = @month".format(
                    self.s("v_confirmed_price")
                ),
                p,
            )
        ]
        readings = [
            from_dict(MeterReading, r)
            for r in self.ex.query(
                "SELECT plant_id, date, cumulative_kwh FROM {} WHERE date BETWEEN @d_from AND @d_to".format(
                    self.s("v_meter_cumulative")
                ),
                {
                    "d_from": month_start(month) - dt.timedelta(days=2),
                    "d_to": next_month_start(month) + dt.timedelta(days=2),
                },
            )
        ]
        population = [
            Decimal(str(r["daily_hours"]))
            for r in self.ex.query(
                "SELECT daily_hours FROM {} WHERE month < @month AND month >= @from_month".format(
                    self.s("v_daily_hours_history")
                ),
                {"month": month, "from_month": _shift_month(month, -12)},
            )
        ]
        return SourceBundle(
            month=month,
            plants=self.plants(),
            journals=journals,
            invoices=invoices,
            tax_invoices=taxes,
            prices=prices,
            meter_readings=readings,
            hours_population=population,
        )


def _shift_month(month: str, delta: int) -> str:
    y, m = int(month[:4]), int(month[5:7])
    idx = y * 12 + (m - 1) + delta
    return "{:04d}-{:02d}".format(idx // 12, idx % 12 + 1)


# ─────────────────────────────── 결과 저장소 (append-only) ───────────────────────────────


class BigQueryExceptions(_Base):
    LATEST = """
      SELECT * EXCEPT(rn) FROM (
        SELECT *, ROW_NUMBER() OVER (PARTITION BY exception_id ORDER BY version DESC) AS rn
        FROM {table}
      ) WHERE rn = 1
    """

    def list(self, month: Optional[str] = None, plant_id: Optional[str] = None) -> List[SettlementException]:
        sql = self.LATEST.format(table=self.t("exception_versions"))
        params: Dict[str, Any] = {}
        if month:
            sql += " AND month = @month"
            params["month"] = month
        if plant_id:
            sql += " AND plant_id = @plant_id"
            params["plant_id"] = plant_id
        sql += " ORDER BY exception_id"
        return [from_dict(SettlementException, r) for r in self.ex.query(sql, params)]

    def get(self, exception_id: str) -> Optional[SettlementException]:
        sql = self.LATEST.format(table=self.t("exception_versions")) + " AND exception_id = @id"
        rows = self.ex.query(sql, {"id": exception_id})
        return from_dict(SettlementException, rows[0]) if rows else None

    def history(self, exception_id: str) -> List[SettlementException]:
        rows = self.ex.query(
            "SELECT * FROM {} WHERE exception_id = @id ORDER BY version".format(self.t("exception_versions")),
            {"id": exception_id},
        )
        return [from_dict(SettlementException, r) for r in rows]

    def save(self, exc: SettlementException) -> None:
        row = to_dict(exc)
        row["recorded_at"] = _now()
        self.ex.insert(self.table_id("exception_versions"), [row])


class BigQueryAdjustments(_Base):
    def list(self, month: str) -> List[Adjustment]:
        rows = self.ex.query(
            "SELECT * FROM {} WHERE month = @month ORDER BY recorded_at".format(self.t("adjustments")), {"month": month}
        )
        return [from_dict(Adjustment, r) for r in rows]

    def add(self, adjustments: List[Adjustment]) -> None:
        rows = []
        for a in adjustments:
            row = to_dict(a)
            row.pop("kwh_delta", None)
            row["recorded_at"] = _now()
            rows.append(row)
        self.ex.insert(self.table_id("adjustments"), rows)


class BigQueryHolds(_Base):
    def list(self, month: str) -> List[Hold]:
        rows = self.ex.query(
            """
            SELECT * EXCEPT(rn) FROM (
              SELECT *, ROW_NUMBER() OVER (PARTITION BY plant_id ORDER BY recorded_at DESC) AS rn
              FROM {} WHERE month = @month
            ) WHERE rn = 1
            """.format(self.t("holds")),
            {"month": month},
        )
        return [from_dict(Hold, r) for r in rows]

    def history(self, month: str, plant_id: str) -> List[Hold]:
        rows = self.ex.query(
            "SELECT * FROM {} WHERE month = @month AND plant_id = @plant_id ORDER BY recorded_at".format(self.t("holds")),
            {"month": month, "plant_id": plant_id},
        )
        return [from_dict(Hold, r) for r in rows]

    def save(self, hold: Hold) -> None:
        row = to_dict(hold)
        row["recorded_at"] = _now()
        self.ex.insert(self.table_id("holds"), [row])


class BigQueryErrorCases(_Base):
    def list(self, month: Optional[str] = None) -> List[ErrorCase]:
        sql = "SELECT * FROM {}".format(self.t("error_cases"))
        params: Dict[str, Any] = {}
        if month:
            sql += " WHERE month = @month"
            params["month"] = month
        return [from_dict(ErrorCase, r) for r in self.ex.query(sql + " ORDER BY case_no", params)]

    def add(self, case: ErrorCase) -> None:
        row = to_dict(case)
        row["recorded_at"] = _now()
        self.ex.insert(self.table_id("error_cases"), [row])


class BigQueryRuns(_Base):
    """대조 결과 스냅샷. 재검증으로 결과가 바뀌면 같은 run_id 로 새 스냅샷을 추가한다."""

    def save(self, run: ReconcileRun) -> None:
        payload = to_dict(run)
        self.ex.insert(
            self.table_id("run_snapshots"),
            [
                {
                    "run_id": run.run_id,
                    "month": run.month,
                    "created_at": run.created_at.isoformat(),
                    "created_by": run.created_by,
                    "saved_at": _now(),
                    "payload": json.dumps(payload, ensure_ascii=False),
                }
            ],
        )

    def _one(self, sql: str, params: Dict[str, Any]) -> Optional[ReconcileRun]:
        rows = self.ex.query(sql, params)
        if not rows:
            return None
        payload = rows[0]["payload"]
        return from_dict(ReconcileRun, json.loads(payload) if isinstance(payload, str) else payload)

    def get(self, run_id: str) -> Optional[ReconcileRun]:
        return self._one(
            "SELECT payload FROM {} WHERE run_id = @run_id ORDER BY saved_at DESC LIMIT 1".format(self.t("run_snapshots")),
            {"run_id": run_id},
        )

    def latest(self, month: str) -> Optional[ReconcileRun]:
        return self._one(
            "SELECT payload FROM {} WHERE month = @month ORDER BY created_at DESC, saved_at DESC LIMIT 1".format(
                self.t("run_snapshots")
            ),
            {"month": month},
        )


class BigQueryRechecks(_Base):
    def add(self, record: RecheckRecord) -> None:
        row = to_dict(record)
        row["evidence"] = json.dumps(row["evidence"], ensure_ascii=False)
        row["recorded_at"] = _now()
        self.ex.insert(self.table_id("rechecks"), [row])

    def list(self, month: str, plant_id: Optional[str] = None) -> List[RecheckRecord]:
        sql = "SELECT * FROM {} WHERE month = @month".format(self.t("rechecks"))
        params: Dict[str, Any] = {"month": month}
        if plant_id:
            sql += " AND plant_id = @plant_id"
            params["plant_id"] = plant_id
        out = []
        for r in self.ex.query(sql + " ORDER BY recorded_at", params):
            r = dict(r)
            if isinstance(r.get("evidence"), str):
                r["evidence"] = json.loads(r["evidence"])
            out.append(from_dict(RecheckRecord, r))
        return out


class BigQueryApprovals(_Base):
    def get(self, month: str) -> Optional[Approval]:
        rows = self.ex.query(
            "SELECT * FROM {} WHERE month = @month ORDER BY at DESC LIMIT 1".format(self.t("approvals")), {"month": month}
        )
        return from_dict(Approval, rows[0]) if rows else None

    def add(self, approval: Approval) -> None:
        row = to_dict(approval)
        row["recorded_at"] = _now()
        self.ex.insert(self.table_id("approvals"), [row])


def bigquery_repositories(executor: Optional[Executor] = None) -> Repositories:
    project = os.environ["AX_BQ_PROJECT"]
    src = os.environ.get("AX_BQ_SRC_DATASET", "ax_settlement_src")
    app = os.environ.get("AX_BQ_APP_DATASET", "ax_settlement")
    ex = executor or BigQueryExecutor(project, os.environ.get("AX_BQ_LOCATION", "asia-northeast3"))
    args = (ex, project, src, app)
    return Repositories(
        source=BigQuerySource(*args),
        exceptions=BigQueryExceptions(*args),
        adjustments=BigQueryAdjustments(*args),
        holds=BigQueryHolds(*args),
        error_cases=BigQueryErrorCases(*args),
        runs=BigQueryRuns(*args),
        rechecks=BigQueryRechecks(*args),
        approvals=BigQueryApprovals(*args),
    )
