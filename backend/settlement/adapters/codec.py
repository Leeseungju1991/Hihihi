"""dataclass ↔ dict(JSON) 왕복 변환. BigQuery 행/JSON 컬럼 저장용."""
from __future__ import annotations

import dataclasses
import datetime as dt
import sys
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, Type, TypeVar, Union, get_type_hints

from ..api.serialize import dump

T = TypeVar("T")

try:  # 3.8 호환
    from typing import get_args, get_origin
except ImportError:  # pragma: no cover
    def get_origin(tp):  # type: ignore
        return getattr(tp, "__origin__", None)

    def get_args(tp):  # type: ignore
        return getattr(tp, "__args__", ())


def to_dict(obj: Any) -> Any:
    return dump(obj)


def _decode(tp: Any, value: Any) -> Any:
    if value is None:
        return None
    origin = get_origin(tp)
    if origin is Union:
        args = [a for a in get_args(tp) if a is not type(None)]
        return _decode(args[0], value) if args else value
    if origin in (list, tuple):
        (inner,) = get_args(tp)[:1] or (Any,)
        return [_decode(inner, v) for v in value]
    if origin is dict:
        k, v = get_args(tp)
        return {_decode(k, kk): _decode(v, vv) for kk, vv in value.items()}
    if tp is Any:
        return value
    if isinstance(tp, type):
        if dataclasses.is_dataclass(tp):
            return from_dict(tp, value)
        if issubclass(tp, Enum):
            return tp(value)
        if tp is Decimal:
            return Decimal(str(value))
        if tp is dt.datetime:
            return value if isinstance(value, dt.datetime) else dt.datetime.fromisoformat(str(value))
        if tp is dt.date:
            if isinstance(value, dt.datetime):
                return value.date()
            return value if isinstance(value, dt.date) else dt.date.fromisoformat(str(value))
        if tp in (str, int, float, bool):
            return tp(value)
    return value


def from_dict(cls: Type[T], data: Dict[str, Any]) -> T:
    module = sys.modules[cls.__module__]
    hints = get_type_hints(cls, vars(module))
    kwargs = {}
    for f in dataclasses.fields(cls):  # type: ignore[arg-type]
        if f.name in data:
            kwargs[f.name] = _decode(hints[f.name], data[f.name])
    return cls(**kwargs)  # type: ignore[call-arg]
