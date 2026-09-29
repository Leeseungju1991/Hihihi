"""정산 오케스트레이터 도메인 모델.

외부 의존성 없는 순수 dataclass 로만 구성한다 (Python 3.8 호환).
- 금액(원)·발전량(kWh)·단가(원/kWh)는 모두 Decimal.
- 원천 행(Journal/SalesInvoice/TaxInvoice/...)은 운영 DB 의 "정규화 뷰" 한 행에 대응한다.
  실제 컬럼 ↔ 정규화 컬럼 매핑은 dataform/definitions/sources/*.sqlx 에서만 한다.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional


# ─────────────────────────────── 열거형 ───────────────────────────────


class Category(str, Enum):
    """3자 대조 결과 5분류."""

    PASS = "PASS"  # 통과
    AUTOMATABLE = "AUTOMATABLE"  # 자동화 대상
    REVIEW = "REVIEW"  # 확인 대상
    HOLD = "HOLD"  # 보류
    ERROR = "ERROR"  # 에러


class IssueTag(str, Enum):
    """확인 대상 유형 태그."""

    METER_SHORTAGE = "METER_SHORTAGE"  # 검침 부족
    DOUBLE_COUNT = "DOUBLE_COUNT"  # 이중계상 의심
    PARTNER_MISMATCH = "PARTNER_MISMATCH"  # 조합 불일치
    HOURS_EXCEEDED = "HOURS_EXCEEDED"  # 발전시간 초과
    INVALID_TAX_INVOICE = "INVALID_TAX_INVOICE"  # 무효 계산서


class Priority(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ExceptionType(str, Enum):
    TRANSFER = "TRANSFER"  # 양수도
    MANUAL_ISSUE = "MANUAL_ISSUE"  # 수기 발행
    PARTNER_CHANGE = "PARTNER_CHANGE"  # 거래처 변경
    PPA_DELAY = "PPA_DELAY"  # PPA 변경 지연
    OTHER = "OTHER"  # 기타


# 기준일로 발전량을 일할 안분하는 예외 유형
SPLIT_EXCEPTION_TYPES = (
    ExceptionType.TRANSFER,
    ExceptionType.PARTNER_CHANGE,
    ExceptionType.PPA_DELAY,
)


class ExceptionStatus(str, Enum):
    REGISTERED = "REGISTERED"  # 등록
    ACTIVE = "ACTIVE"  # 적용 중
    CLOSED = "CLOSED"  # 종료


class TaxInvoiceStatus(str, Enum):
    VALID = "VALID"
    DISABLE = "DISABLE"  # 무효


class InvoiceSource(str, Enum):
    SYSTEM = "SYSTEM"  # pv_sales_invoice
    MANUAL = "MANUAL"  # 예외(수기 발행)로 결합된 가상 송장


class Basis(str, Enum):
    """보정값 근거 — 리포트의 추정/실제 구분."""

    ACTUAL = "ACTUAL"  # 검침 누적값 차이 등 실측
    ESTIMATED = "ESTIMATED"  # 인근 발전소 기반 추정


class AdjustmentKind(str, Enum):
    MANUAL_INVOICE = "MANUAL_INVOICE"  # 수기 송장 결합
    PRORATION = "PRORATION"  # 양수도/거래처/PPA 일할 안분
    METER_CORRECTION = "METER_CORRECTION"  # 누락 검침량 보정


# ─────────────────────────────── 원천 데이터 (읽기 전용) ───────────────────────────────


@dataclass(frozen=True)
class Plant:
    plant_id: str
    name: str
    capacity_kw: Decimal
    region: str = ""
    partner_id: str = ""  # 현재 조합(거래처)


@dataclass(frozen=True)
class JournalEntry:
    """분개장 412 (pv_biz_bal_item)."""

    entry_id: str
    plant_id: str
    month: str  # "YYYY-MM"
    partner_id: str
    amount: Decimal


@dataclass(frozen=True)
class SalesInvoice:
    """송장 (pv_sales_invoice)."""

    invoice_id: str
    plant_id: str
    month: str
    partner_id: str
    meter_kwh: Decimal
    amount: Decimal
    source: InvoiceSource = InvoiceSource.SYSTEM


@dataclass(frozen=True)
class TaxInvoice:
    """세금계산서 (stg_nts_tax_invoice)."""

    nts_id: str
    plant_id: str
    month: str
    partner_id: str
    supply_amount: Decimal
    status: TaxInvoiceStatus
    issue_date: Optional[dt.date] = None


@dataclass(frozen=True)
class ConfirmedPrice:
    """한전 확정 단가(SMP 등). plant_id 가 빈 문자열이면 해당 월 공통 단가."""

    month: str
    unit_price: Decimal
    plant_id: str = ""


@dataclass(frozen=True)
class MeterReading:
    """모니터링(RTU) 누적 발전량 스냅샷."""

    plant_id: str
    date: dt.date
    cumulative_kwh: Decimal


@dataclass
class SourceBundle:
    """한 정산월의 원천 데이터 묶음."""

    month: str
    plants: Dict[str, Plant]
    journals: List[JournalEntry]
    invoices: List[SalesInvoice]
    tax_invoices: List[TaxInvoice]
    prices: List[ConfirmedPrice]
    meter_readings: List[MeterReading] = field(default_factory=list)
    # 발전시간 상한 계산용 모집단(과거 월 일평균 발전시간). 비어있으면 당월 전체 발전소로 계산.
    hours_population: List[Decimal] = field(default_factory=list)

    def counts(self) -> Dict[str, int]:
        return {
            "journal": len(self.journals),
            "invoice": len(self.invoices),
            "tax_invoice": len(self.tax_invoices),
        }


# ─────────────────────────────── 사용자 입력 (별도 테이블) ───────────────────────────────


@dataclass
class SettlementException:
    """예외 관리 페이지에서 등록하는 정형 예외."""

    exception_id: str
    month: str
    plant_id: str
    type: ExceptionType
    status: ExceptionStatus = ExceptionStatus.REGISTERED
    base_date: Optional[dt.date] = None
    partner_before: str = ""
    partner_after: str = ""
    manual_kwh: Optional[Decimal] = None
    note: str = ""
    version: int = 1
    updated_by: str = ""
    updated_at: Optional[dt.datetime] = None


@dataclass
class Adjustment:
    """보정 테이블 한 행. 검침량·일평균 발전시간만 바꾸며 금액은 절대 바꾸지 않는다."""

    adjustment_id: str
    month: str
    plant_id: str
    kind: AdjustmentKind
    partner_id: str
    kwh_before: Decimal
    kwh_after: Decimal
    basis: Basis
    formula: str
    exception_id: str = ""
    applied_by: str = ""
    applied_at: Optional[dt.datetime] = None
    # 되돌림 행이면 원래 adjustment_id. 자동화 후 재검증 미통과 시 append-only 로 되돌린다.
    reverts: str = ""

    @property
    def kwh_delta(self) -> Decimal:
        return self.kwh_after - self.kwh_before


@dataclass
class Hold:
    month: str
    plant_id: str
    reason: str
    actor: str
    at: dt.datetime
    released: bool = False
    released_by: str = ""
    released_at: Optional[dt.datetime] = None


@dataclass
class ErrorCase:
    case_no: str
    occurred_on: dt.date
    month: str
    plant_id: str
    symptom: str
    created_by: str = ""


# ─────────────────────────────── 대조 결과 ───────────────────────────────


@dataclass
class Evidence:
    """근거 데이터. LLM 설명에 인용되는 값은 반드시 이 목록의 값이어야 한다."""

    key: str
    label: str
    value: str


@dataclass
class PlantResult:
    plant_id: str
    plant_name: str
    month: str
    category: Category
    journal_amount: Decimal = Decimal("0")
    invoice_kwh: Decimal = Decimal("0")
    invoice_amount: Decimal = Decimal("0")  # 검침량 × 확정 단가
    tax_amount: Decimal = Decimal("0")
    unit_price: Optional[Decimal] = None
    implied_price: Optional[Decimal] = None  # 분개 ÷ 검침량
    implied_kwh: Optional[Decimal] = None  # 분개 ÷ 확정 단가
    daily_hours: Optional[Decimal] = None
    tags: List[IssueTag] = field(default_factory=list)
    summary: str = ""  # 문제 한 줄
    priority: Priority = Priority.LOW
    evidence: List[Evidence] = field(default_factory=list)
    applied_exception_ids: List[str] = field(default_factory=list)
    applied_adjustment_ids: List[str] = field(default_factory=list)
    candidate_adjustments: List[Adjustment] = field(default_factory=list)
    error: str = ""

    @property
    def amount_diff(self) -> Decimal:
        """분개 대비 세금계산서 차이(원)."""
        return self.tax_amount - self.journal_amount

    @property
    def kwh_diff(self) -> Optional[Decimal]:
        if self.implied_kwh is None:
            return None
        return self.invoice_kwh - self.implied_kwh


@dataclass
class ReconcileRun:
    run_id: str
    month: str
    created_at: dt.datetime
    created_by: str
    counts: Dict[str, int]
    results: List[PlantResult]

    def by_category(self) -> Dict[str, int]:
        out = {c.value: 0 for c in Category}
        for r in self.results:
            out[r.category.value] += 1
        return out


@dataclass
class RecheckRecord:
    month: str
    plant_id: str
    attempt: int
    passed: bool
    category: Category
    cause: str
    recommended_action: str
    evidence: List[Evidence]
    actor: str
    at: dt.datetime
    trigger: str  # "AUTOMATION" | "MANUAL"
    # 자동화 재검증일 때 시도한 보정 묶음의 서명. 같은 묶음이 다시 자동화 대상으로 뜨지 않게 한다.
    tried_signature: str = ""


@dataclass
class Approval:
    month: str
    actor: str
    at: dt.datetime
    open_holds: List[str]
    note: str = ""
