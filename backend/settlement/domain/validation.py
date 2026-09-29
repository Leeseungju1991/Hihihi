"""예외 입력 검증 — 유형별 필수값 즉시 검증 (프론트와 동일 규칙, 서버가 최종 판정)."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Dict, List

from .models import ExceptionType, SettlementException, SPLIT_EXCEPTION_TYPES

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ValidationError(ValueError):
    def __init__(self, errors: Dict[str, str]):
        super().__init__("; ".join("{}: {}".format(k, v) for k, v in errors.items()))
        self.errors = errors


# 유형별 필수 필드 — 프론트 폼이 이 표를 그대로 쓴다 (GET /meta/exception-types)
REQUIRED_FIELDS: Dict[ExceptionType, List[str]] = {
    ExceptionType.TRANSFER: ["base_date", "partner_before", "partner_after"],
    ExceptionType.PARTNER_CHANGE: ["base_date", "partner_before", "partner_after"],
    ExceptionType.PPA_DELAY: ["base_date", "partner_before", "partner_after"],
    ExceptionType.MANUAL_ISSUE: ["manual_kwh", "partner_after"],
    ExceptionType.OTHER: ["note"],
}


def validate_month(month: str) -> None:
    if not MONTH_RE.match(month or ""):
        raise ValidationError({"month": "YYYY-MM 형식이어야 합니다"})


def validate_exception(exc: SettlementException, known_plants=None) -> None:
    errors: Dict[str, str] = {}
    if not MONTH_RE.match(exc.month or ""):
        errors["month"] = "YYYY-MM 형식이어야 합니다"
    if not exc.plant_id:
        errors["plant_id"] = "발전소를 선택하세요"
    elif known_plants is not None and exc.plant_id not in known_plants:
        errors["plant_id"] = "발전소 마스터에 없는 발전소입니다"

    for name in REQUIRED_FIELDS[exc.type]:
        value = getattr(exc, name)
        if value is None or (isinstance(value, str) and not value.strip()):
            errors[name] = "필수 입력입니다"

    if exc.type in SPLIT_EXCEPTION_TYPES:
        if exc.base_date is not None and "month" not in errors:
            if exc.base_date.strftime("%Y-%m") != exc.month:
                errors["base_date"] = "기준일은 정산월 안의 날짜여야 합니다"
        if exc.partner_before and exc.partner_before == exc.partner_after:
            errors["partner_after"] = "변경 전·후 조합이 같습니다"

    if exc.type == ExceptionType.MANUAL_ISSUE and exc.manual_kwh is not None:
        if exc.manual_kwh <= Decimal("0"):
            errors["manual_kwh"] = "0보다 커야 합니다"

    if errors:
        raise ValidationError(errors)
