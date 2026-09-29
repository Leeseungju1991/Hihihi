"""dataclass → JSON. 금액·kWh(Decimal)는 부동소수 오차를 피하려고 문자열로 내보낸다."""
from __future__ import annotations

import dataclasses
import datetime as dt
from decimal import Decimal
from enum import Enum
from typing import Any


def dump(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        out = {f.name: dump(getattr(obj, f.name)) for f in dataclasses.fields(obj)}
        # 계산 프로퍼티 노출
        for prop in ("amount_diff", "kwh_diff", "kwh_delta"):
            if hasattr(type(obj), prop):
                out[prop] = dump(getattr(obj, prop))
        return out
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, Decimal):
        return str(obj)
    if isinstance(obj, (dt.datetime, dt.date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {str(k): dump(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [dump(v) for v in obj]
    return obj
