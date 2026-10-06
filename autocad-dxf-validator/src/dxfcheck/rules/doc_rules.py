"""도면 표기 규칙 — 표제란·축척·개정 이력·범례 등 설계도서로서의 완결성."""
from __future__ import annotations

from typing import Dict, Iterable, List

from ..model import Category, Finding, Severity
from . import Context, rule

D = Category.DOC

TITLE_ITEMS: Dict[str, List[str]] = {
    "공사명": ["공사명", "사업명", "건명", "PROJECT", "PROJECTNAME"],
    "도면명": ["도면명", "DWGTITLE", "DRAWINGTITLE", "DWGNAME", "TITLE"],
    "도면번호": ["도면번호", "도번", "DWGNO", "DRAWINGNO", "SHEETNO"],
    "축척": ["축척", "SCALE"],
    "작성일": ["일자", "날짜", "작성일", "DATE"],
    "설계자": ["설계", "작성자", "DESIGNED", "DESIGN", "DRAWN"],
    "검토·승인": ["검토", "승인", "확인", "CHECKED", "APPROVED", "REVIEWED"],
}


def _key(s: str) -> str:
    return s.upper().replace(" ", "").replace(".", "").replace("_", "")


def _corpus(ctx: Context) -> str:
    parts = [_key(t.norm) for t in ctx.drawing.texts]
    for _, attrs, _ in ctx.drawing.inserts_attribs:
        parts.extend(_key(k) for k in attrs)
    return "\n".join(parts)


@rule
def title_block(ctx: Context) -> Iterable[Finding]:
    if not ctx.drawing.texts and not ctx.drawing.inserts_attribs:
        yield Finding("DOC-001", D, Severity.WARNING, "문자 없음",
                      "도면에 문자가 없어 표제란·설비 표기를 검토할 수 없습니다.")
        return
    corpus = _corpus(ctx)
    missing = [name for name, words in TITLE_ITEMS.items() if not any(w in corpus for w in words)]
    if len(missing) == len(TITLE_ITEMS):
        yield Finding("DOC-001", D, Severity.ERROR, "표제란 없음",
                      "공사명·도면명·도면번호·축척·작성일·설계자 표기를 찾지 못했습니다. 설계도서로 쓰려면 표제란이 필요합니다.",
                      "KS A 0005 제도통칙 · 전력기술관리법(설계도서)")
    elif missing:
        yield Finding("DOC-001", D, Severity.WARNING, "표제란 항목 누락",
                      "표제란에서 다음 항목을 찾지 못했습니다: %s" % ", ".join(missing),
                      "KS A 0005 제도통칙", evidence=missing)


@rule
def empty_attributes(ctx: Context) -> Iterable[Finding]:
    title_words = [w for words in TITLE_ITEMS.values() for w in words]
    for block, attrs, handle in ctx.drawing.inserts_attribs:
        empty = [t for t, v in attrs.items() if not v and any(w in _key(t) for w in title_words)]
        if empty:
            yield Finding("DOC-002", D, Severity.WARNING, "표제란 속성 미기입",
                          "블록 '%s'의 속성이 비어 있습니다: %s" % (block, ", ".join(empty)),
                          location={"handle": handle, "block": block})


@rule
def scale(ctx: Context) -> Iterable[Finding]:
    corpus = _corpus(ctx)
    if ctx.scale is None and ("축척" in corpus or "SCALE" in corpus):
        if "NONE" in corpus or "NS" in corpus.split() or "없음" in corpus:
            return
        yield Finding("DOC-003", D, Severity.INFO, "축척 값 판독 불가",
                      "축척 항목은 있으나 '1/100' 형식 값을 찾지 못했습니다(계통도는 NONE 표기 가능).")


@rule
def revision(ctx: Context) -> Iterable[Finding]:
    corpus = _corpus(ctx)
    if ctx.drawing.texts and not any(w in corpus for w in ("REV", "개정", "변경내용", "REVISION")):
        yield Finding("DOC-004", D, Severity.INFO, "개정 이력란 없음",
                      "개정(REV) 이력란을 찾지 못했습니다. 변경 추적을 위해 개정란을 권장합니다.")


@rule
def legend(ctx: Context) -> Iterable[Finding]:
    if not ctx.elec.is_electrical:
        return
    corpus = _corpus(ctx)
    if not any(w in corpus for w in ("범례", "LEGEND", "기호", "SYMBOL")):
        yield Finding("DOC-005", D, Severity.INFO, "범례 없음",
                      "전기 설비 표기가 있으나 범례(LEGEND)를 찾지 못했습니다. 기호 해석 기준을 함께 제시하세요.",
                      "KS C 0102 전기용 기호")


@rule
def designer_seal(ctx: Context) -> Iterable[Finding]:
    if not ctx.elec.is_electrical:
        return
    corpus = _corpus(ctx)
    if not any(w in corpus for w in ("전기기술사", "설계사무소", "감리", "설계자", "DESIGNED", "엔지니어링")):
        yield Finding("DOC-006", D, Severity.INFO, "설계자 표기 확인",
                      "전기설계도서는 전기 분야 설계자(설계업자) 표기·날인이 필요합니다. 표기를 찾지 못했습니다.",
                      "전력기술관리법(설계도서 작성·날인)")
