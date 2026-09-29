"""가상 시나리오 데이터 (실데이터 아님). 로컬 개발 서버와 테스트가 공유한다.

정산월 2026-08 (31일), 확정 단가 120.5원/kWh.

| 발전소 | 시나리오                          | 기대 분류          | 자동화 후        |
|--------|-----------------------------------|--------------------|------------------|
| P001~3 | 정상 (지역 A)                     | 통과               | -                |
| P004   | RTU 누락 → 검침 부족, 누적값 있음 | 자동화(실제 보정)  | 통과             |
| P005   | 수기 발행분 송장 누락 + 예외 등록 | 자동화(수기 결합)  | 통과             |
| P006   | 양수도(8/11) 발행 지연 + 예외 등록| 자동화(일할 안분)  | 통과             |
| P007   | 무효 계산서 정상 처리             | 통과               | -                |
| P008   | 음수 계산서가 유효로 남음         | 확인(무효 계산서)  | -                |
| P009   | 송장 중복                         | 확인(이중계상)     | -                |
| P010   | 설비용량 대비 발전시간 과다       | 확인(발전시간 초과)| -                |
| P011   | 송장·세금계산서 없음              | 에러               | -                |
| P012   | 검침 부족, 누적값 없음            | 자동화(추정 보정)  | 미통과           |
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal as D
from typing import Dict, List

from .engine.numbers import month_start, next_month_start
from .domain.models import (
    ConfirmedPrice,
    ExceptionType,
    InvoiceSource,
    JournalEntry,
    MeterReading,
    Plant,
    SalesInvoice,
    SettlementException,
    SourceBundle,
    TaxInvoice,
    TaxInvoiceStatus,
)

MONTH = "2026-08"
PRICE = D("120.5")


def _amt(kwh: int) -> D:
    return (D(kwh) * PRICE).quantize(D("1"))


def demo_bundle(month: str = MONTH) -> SourceBundle:
    """같은 시나리오를 다른 정산월로 만들 수 있다 (31일 달이면 기대값 동일)."""
    plants: Dict[str, Plant] = {}
    journals: List[JournalEntry] = []
    invoices: List[SalesInvoice] = []
    taxes: List[TaxInvoice] = []
    seq = {"j": 0, "i": 0, "t": 0}

    def plant(pid: str, name: str, cap: int, region: str, partner: str = "C-SOLAR1") -> None:
        plants[pid] = Plant(pid, name, D(cap), region, partner)

    def jnl(pid: str, amount: D, partner: str = "C-SOLAR1") -> None:
        seq["j"] += 1
        journals.append(JournalEntry("J{:04d}".format(seq["j"]), pid, month, partner, amount))

    def inv(pid: str, kwh: int, partner: str = "C-SOLAR1") -> None:
        seq["i"] += 1
        invoices.append(SalesInvoice("I{:04d}".format(seq["i"]), pid, month, partner, D(kwh), _amt(kwh), InvoiceSource.SYSTEM))

    def tax(pid: str, amount: D, partner: str = "C-SOLAR1", status: TaxInvoiceStatus = TaxInvoiceStatus.VALID) -> None:
        seq["t"] += 1
        taxes.append(TaxInvoice("NTS{:04d}".format(seq["t"]), pid, month, partner, amount, status, next_month_start(month) + dt.timedelta(days=9)))

    def normal(pid: str, kwh: int) -> None:
        jnl(pid, _amt(kwh))
        inv(pid, kwh)
        tax(pid, _amt(kwh))

    plant("P001", "햇살1호", 100, "A")
    normal("P001", 10850)
    plant("P002", "햇살2호", 200, "A")
    normal("P002", 20150)
    plant("P003", "햇살3호", 50, "A")
    normal("P003", 5270)

    # P004 RTU 누락: 송장 9,000 / 실제 10,850
    plant("P004", "바람들4호", 100, "B")
    jnl("P004", _amt(10850))
    inv("P004", 9000)
    tax("P004", _amt(10850))

    # P005 수기 발행 2,850kWh 가 시스템 송장에 없음
    plant("P005", "들판5호", 100, "B")
    jnl("P005", _amt(10850))
    inv("P005", 8000)
    tax("P005", _amt(8000))
    tax("P005", _amt(2850))

    # P006 양수도 2026-08-11 (C-SOLAR1 → C-SOLAR2), 송장은 전량 이전 조합으로 발행됨
    plant("P006", "언덕6호", 100, "B", partner="C-SOLAR2")
    jnl("P006", _amt(3500), "C-SOLAR1")
    jnl("P006", _amt(7350), "C-SOLAR2")
    inv("P006", 10850, "C-SOLAR1")
    tax("P006", _amt(3500), "C-SOLAR1")
    tax("P006", _amt(7350), "C-SOLAR2")

    # P007 무효 계산서 올바르게 무효 처리 + 재발행
    plant("P007", "강변7호", 100, "B")
    jnl("P007", _amt(10850))
    inv("P007", 10850)
    tax("P007", _amt(10850), status=TaxInvoiceStatus.DISABLE)
    tax("P007", -_amt(10850), status=TaxInvoiceStatus.DISABLE)
    tax("P007", _amt(10850))

    # P008 음수 계산서가 유효로 남아 합계 0
    plant("P008", "강변8호", 100, "B")
    jnl("P008", _amt(10850))
    inv("P008", 10850)
    tax("P008", _amt(10850))
    tax("P008", -_amt(10850))

    # P009 송장 중복
    plant("P009", "산마루9호", 100, "B")
    jnl("P009", _amt(10850))
    inv("P009", 10850)
    inv("P009", 10850)
    tax("P009", _amt(10850))

    # P010 설비 30kW 인데 10,850kWh (일 11.67h)
    plant("P010", "호수10호", 30, "B")
    normal("P010", 10850)

    # P011 분개만 있음
    plant("P011", "들녘11호", 100, "B")
    jnl("P011", _amt(10850))

    # P012 검침 부족, 누적값 없음 → 지역 A 인근 발전소 기반 추정
    plant("P012", "햇살12호", 100, "A")
    jnl("P012", _amt(10850))
    inv("P012", 7000)
    tax("P012", _amt(10850))

    readings = [
        MeterReading("P004", month_start(month), D("500000")),
        MeterReading("P004", next_month_start(month), D("510850")),
    ]

    return SourceBundle(
        month=month,
        plants=plants,
        journals=journals,
        invoices=invoices,
        tax_invoices=taxes,
        prices=[ConfirmedPrice(month, PRICE)],
        meter_readings=readings,
    )


def demo_exceptions(month: str = MONTH) -> List[SettlementException]:
    prefix = "EX-" if month == MONTH else "EX-{}-".format(month.replace("-", ""))
    return [
        SettlementException(
            exception_id=prefix + "0001",
            month=month,
            plant_id="P005",
            type=ExceptionType.MANUAL_ISSUE,
            manual_kwh=D("2850"),
            partner_after="C-SOLAR1",
            note="8월분 수기 발행 (홈택스 직접 발행)",
        ),
        SettlementException(
            exception_id=prefix + "0002",
            month=month,
            plant_id="P006",
            type=ExceptionType.TRANSFER,
            base_date=month_start(month) + dt.timedelta(days=10),
            partner_before="C-SOLAR1",
            partner_after="C-SOLAR2",
            note="양수도 계약 8/11 발효",
        ),
    ]
