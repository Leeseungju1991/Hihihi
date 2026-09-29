"""포트(인터페이스). 규칙 엔진·워크플로는 이 인터페이스만 안다.

- adapters/memory.py   : 로컬/테스트용 메모리 구현 (fixture)
- adapters/bigquery.py : 회사 BigQuery 구현 (원천은 정규화 뷰 읽기 전용, 결과는 별도 데이터셋 append-only)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

try:  # Python 3.8+ 에 typing.Protocol 존재
    from typing import Protocol
except ImportError:  # pragma: no cover
    from typing_extensions import Protocol  # type: ignore

from .domain.models import (
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


class SourceRepository(Protocol):
    """운영 원천 — 읽기 전용. 쓰기 메서드를 두지 않는다."""

    def load(self, month: str) -> SourceBundle: ...

    def plants(self) -> Dict[str, Plant]: ...


class ExceptionRepository(Protocol):
    """버전 append-only. save 는 항상 새 버전 행을 추가한다 (= 이력)."""

    def list(self, month: Optional[str] = None, plant_id: Optional[str] = None) -> List[SettlementException]: ...

    def get(self, exception_id: str) -> Optional[SettlementException]: ...

    def history(self, exception_id: str) -> List[SettlementException]: ...

    def save(self, exc: SettlementException) -> None: ...


class AdjustmentRepository(Protocol):
    def list(self, month: str) -> List[Adjustment]: ...

    def add(self, adjustments: List[Adjustment]) -> None: ...


class HoldRepository(Protocol):
    def list(self, month: str) -> List[Hold]: ...

    def history(self, month: str, plant_id: str) -> List[Hold]: ...

    def save(self, hold: Hold) -> None: ...


class ErrorCaseRepository(Protocol):
    def list(self, month: Optional[str] = None) -> List[ErrorCase]: ...

    def add(self, case: ErrorCase) -> None: ...


class RunRepository(Protocol):
    def save(self, run: ReconcileRun) -> None: ...

    def get(self, run_id: str) -> Optional[ReconcileRun]: ...

    def latest(self, month: str) -> Optional[ReconcileRun]: ...


class RecheckRepository(Protocol):
    def add(self, record: RecheckRecord) -> None: ...

    def list(self, month: str, plant_id: Optional[str] = None) -> List[RecheckRecord]: ...


class ApprovalRepository(Protocol):
    def get(self, month: str) -> Optional[Approval]: ...

    def add(self, approval: Approval) -> None: ...


@dataclass
class Repositories:
    source: SourceRepository
    exceptions: ExceptionRepository
    adjustments: AdjustmentRepository
    holds: HoldRepository
    error_cases: ErrorCaseRepository
    runs: RunRepository
    rechecks: RecheckRepository
    approvals: ApprovalRepository
