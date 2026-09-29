"""수치 유틸 — Decimal 반올림, 퍼센타일, 일수."""
from __future__ import annotations

import calendar
import datetime as dt
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, List, Optional

WON = Decimal("1")
KWH = Decimal("1")
PRICE = Decimal("0.0001")
HOURS = Decimal("0.01")


def q(value: Decimal, unit: Decimal) -> Decimal:
    return value.quantize(unit, rounding=ROUND_HALF_UP)


def days_in_month(month: str) -> int:
    y, m = int(month[:4]), int(month[5:7])
    return calendar.monthrange(y, m)[1]


def month_start(month: str) -> dt.date:
    return dt.date(int(month[:4]), int(month[5:7]), 1)


def next_month_start(month: str) -> dt.date:
    start = month_start(month)
    return (start + dt.timedelta(days=days_in_month(month)))


def percentile(values: Iterable[Decimal], pct: Decimal) -> Optional[Decimal]:
    """선형 보간 퍼센타일 (numpy 기본 방식과 동일)."""
    data: List[Decimal] = sorted(values)
    if not data:
        return None
    if len(data) == 1:
        return data[0]
    rank = (pct / Decimal("100")) * (len(data) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(data) - 1)
    frac = rank - lo
    return data[lo] + (data[hi] - data[lo]) * frac


def median(values: Iterable[Decimal]) -> Optional[Decimal]:
    return percentile(values, Decimal("50"))


def fmt_won(v: Decimal) -> str:
    return "{:,}원".format(int(q(v, WON)))


def fmt_kwh(v: Decimal) -> str:
    return "{:,}kWh".format(int(q(v, KWH)))


def fmt_price(v: Decimal) -> str:
    text = "{:.4f}".format(q(v, PRICE)).rstrip("0").rstrip(".")
    return "{}원/kWh".format(text)
