"""검증 규칙 레지스트리.

규칙은 `Context -> Iterable[Finding]` 함수다. 새 규칙은 해당 모듈에 `@rule` 으로 등록하고
`tests/`에 기대 결과를 적는다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Iterable, List, Optional, Set

from ..config import Settings
from ..drawing import Drawing
from ..electrical import ElectricalModel
from ..model import CircuitRow, Finding


@dataclass
class Context:
    drawing: Drawing
    elec: ElectricalModel
    settings: Settings
    arcname: str
    sibling_files: Set[str] = field(default_factory=set)   # 같은 압축의 파일명(소문자, 경로 제외)
    circuits: List[CircuitRow] = field(default_factory=list)
    scale: Optional[int] = None


RuleFn = Callable[[Context], Iterable[Finding]]
RULES: List[RuleFn] = []


def rule(fn: RuleFn) -> RuleFn:
    RULES.append(fn)
    return fn


def run_all(ctx: Context) -> List[Finding]:
    from . import cad_rules, doc_rules, kec_rules  # noqa: F401  (등록)

    out: List[Finding] = []
    for fn in RULES:
        out.extend(fn(ctx))
    return out


def loc(item=None, **kw) -> dict:
    d = {}
    if item is not None:
        d.update(layer=item.layer, layout=item.layout, handle=item.handle,
                 x=round(item.x, 2), y=round(item.y, 2))
    d.update({k: v for k, v in kw.items() if v not in (None, "")})
    return d
