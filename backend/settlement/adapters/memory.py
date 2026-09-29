"""메모리 구현 — 로컬 개발·테스트용. 회사에서는 adapters/bigquery.py 로 교체."""
from __future__ import annotations

import copy
from typing import Dict, List, Optional

from ..domain.models import (
    Adjustment,
    Approval,
    ErrorCase,
    Hold,
    Plant,
    ReconcileRun,
    RecheckRecord,
    SettlementException,
    SourceBundle,
)
from ..ports import Repositories


class MemorySource:
    def __init__(self, bundles: Dict[str, SourceBundle]):
        self._bundles = bundles

    def load(self, month: str) -> SourceBundle:
        if month not in self._bundles:
            raise LookupError("{} 원천 데이터 없음".format(month))
        return copy.deepcopy(self._bundles[month])

    def plants(self) -> Dict[str, Plant]:
        out: Dict[str, Plant] = {}
        for b in self._bundles.values():
            out.update(b.plants)
        return out


class MemoryExceptions:
    def __init__(self) -> None:
        self._rows: List[SettlementException] = []

    def _latest(self) -> Dict[str, SettlementException]:
        latest: Dict[str, SettlementException] = {}
        for r in self._rows:
            cur = latest.get(r.exception_id)
            if cur is None or r.version > cur.version:
                latest[r.exception_id] = r
        return latest

    def list(self, month: Optional[str] = None, plant_id: Optional[str] = None) -> List[SettlementException]:
        rows = list(self._latest().values())
        if month:
            rows = [r for r in rows if r.month == month]
        if plant_id:
            rows = [r for r in rows if r.plant_id == plant_id]
        return [copy.deepcopy(r) for r in sorted(rows, key=lambda r: r.exception_id)]

    def get(self, exception_id: str) -> Optional[SettlementException]:
        r = self._latest().get(exception_id)
        return copy.deepcopy(r) if r else None

    def history(self, exception_id: str) -> List[SettlementException]:
        return [copy.deepcopy(r) for r in sorted(self._rows, key=lambda r: r.version) if r.exception_id == exception_id]

    def save(self, exc: SettlementException) -> None:
        self._rows.append(copy.deepcopy(exc))


class MemoryAdjustments:
    def __init__(self) -> None:
        self._rows: List[Adjustment] = []

    def list(self, month: str) -> List[Adjustment]:
        return [copy.deepcopy(a) for a in self._rows if a.month == month]

    def add(self, adjustments: List[Adjustment]) -> None:
        self._rows.extend(copy.deepcopy(adjustments))


class MemoryHolds:
    def __init__(self) -> None:
        self._rows: List[Hold] = []

    def list(self, month: str) -> List[Hold]:
        latest: Dict[str, Hold] = {}
        for h in self._rows:
            if h.month == month:
                latest[h.plant_id] = h
        return [copy.deepcopy(h) for h in latest.values()]

    def history(self, month: str, plant_id: str) -> List[Hold]:
        return [copy.deepcopy(h) for h in self._rows if h.month == month and h.plant_id == plant_id]

    def save(self, hold: Hold) -> None:
        self._rows.append(copy.deepcopy(hold))


class MemoryErrorCases:
    def __init__(self) -> None:
        self._rows: List[ErrorCase] = []

    def list(self, month: Optional[str] = None) -> List[ErrorCase]:
        return [copy.deepcopy(c) for c in self._rows if month is None or c.month == month]

    def add(self, case: ErrorCase) -> None:
        self._rows.append(copy.deepcopy(case))


class MemoryRuns:
    def __init__(self) -> None:
        self._runs: Dict[str, ReconcileRun] = {}

    def save(self, run: ReconcileRun) -> None:
        self._runs[run.run_id] = copy.deepcopy(run)

    def get(self, run_id: str) -> Optional[ReconcileRun]:
        r = self._runs.get(run_id)
        return copy.deepcopy(r) if r else None

    def latest(self, month: str) -> Optional[ReconcileRun]:
        runs = [r for r in self._runs.values() if r.month == month]
        return copy.deepcopy(max(runs, key=lambda r: r.created_at)) if runs else None


class MemoryRechecks:
    def __init__(self) -> None:
        self._rows: List[RecheckRecord] = []

    def add(self, record: RecheckRecord) -> None:
        self._rows.append(copy.deepcopy(record))

    def list(self, month: str, plant_id: Optional[str] = None) -> List[RecheckRecord]:
        return [
            copy.deepcopy(r)
            for r in self._rows
            if r.month == month and (plant_id is None or r.plant_id == plant_id)
        ]


class MemoryApprovals:
    def __init__(self) -> None:
        self._rows: Dict[str, Approval] = {}

    def get(self, month: str) -> Optional[Approval]:
        return copy.deepcopy(self._rows.get(month))

    def add(self, approval: Approval) -> None:
        self._rows[approval.month] = copy.deepcopy(approval)


def memory_repositories(bundles: Dict[str, SourceBundle]) -> Repositories:
    return Repositories(
        source=MemorySource(bundles),
        exceptions=MemoryExceptions(),
        adjustments=MemoryAdjustments(),
        holds=MemoryHolds(),
        error_cases=MemoryErrorCases(),
        runs=MemoryRuns(),
        rechecks=MemoryRechecks(),
        approvals=MemoryApprovals(),
    )
