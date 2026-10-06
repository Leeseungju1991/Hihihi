"""태양광 도면 세트(E-01~E-21) 인식과 사실(fact) 추출.

정본 도면 목록은 'AutoCAD 자동화 설계' 문서 6장을 따른다. 각 도면에서 설비용량·모듈 수·
직병렬·DC 퓨즈·MPPT 등 '사실'을 문자에서 뽑아, 세트 규칙(rules/set_rules.py)이 도면 간·
메타데이터와 대조한다.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Dict, List, Optional, Tuple

from .config import Settings
from .drawing import Drawing, TextItem, normalize
from .electrical import ElectricalModel

# 도면번호 → (정본 도면명, 내용 확인 키워드)
CATALOG: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "E-01": ("도면 목록표", ("목록", "INDEX")),
    "E-02": ("공사 개요", ("개요", "OVERVIEW")),
    "E-03": ("전력인입배치도", ("인입", "배치")),
    "E-04": ("단선결선도(SLD)", ("단선", "결선도", "SLD", "SINGLE LINE")),
    "E-05": ("전력간선도", ("간선",)),
    "E-06": ("접지설비평면도", ("접지",)),
    "E-07": ("ARRAY 구조물 접지 상세도", ("접지",)),
    "E-08": ("모듈결선도", ("모듈", "결선")),
    "E-09": ("태양광발전설비 계통도", ("계통",)),
    "E-10": ("ARRAY 계통도", ("ARRAY", "계통")),
    "E-11": ("DC 전력 간선도", ("DC", "간선")),
    "E-12": ("모듈 상세도", ("모듈",)),
    "E-13": ("인버터 회로도", ("인버터", "회로")),
    "E-14": ("인버터 외형도", ("인버터", "외형")),
    "E-15": ("LV-M(계량기형) 외형도", ("LV-M", "계량기", "외형")),
    "E-16": ("울타리/대문 상세도", ("울타리", "대문", "휀스", "펜스", "FENCE")),
    "E-17": ("케이블트레이 상세도(1)", ("트레이", "TRAY")),
    "E-18": ("케이블트레이 상세도(2)", ("트레이", "TRAY")),
    "E-19": ("구조물 상세도(1)", ("구조물",)),
    "E-20": ("구조물 상세도(2)", ("구조물",)),
    "E-21": ("MPPT 구성도", ("MPPT",)),
}
CONDITIONAL = {"E-15"}   # 저압 수전일 때만

NO_RE = re.compile(r"(?<![A-Z0-9])E\s*-?\s*(\d{1,2})(?:\s*-\s*(\d{1,2}))?(?!\d)")
_NO_TAGS = ("도면번호", "DWGNO", "DRAWINGNO", "SHEETNO", "도번")
_TITLE_TAGS = ("도면명", "DWGTITLE", "DRAWINGTITLE", "DWGNAME", "TITLE")


def _tagkey(s: str) -> str:
    return s.upper().replace(" ", "").replace(".", "").replace("_", "")


def corpus_key(s: str) -> str:
    """도면 문자 비교용 키: 정규화 후 공백·괄호·구분기호 제거."""
    return re.sub(r"[\s()\[\]/·.\-_]", "", normalize(s))


def _fmt_no(m) -> Tuple[str, Optional[int]]:
    return "E-%02d" % int(m.group(1)), (int(m.group(2)) if m.group(2) else None)


def detect_number(arcname: str, d: Drawing) -> Tuple[Optional[str], Optional[int], str]:
    """(도면번호, 하위 페이지, 근거)."""
    stem = normalize(PurePosixPath(arcname).stem)
    m = NO_RE.search(stem)
    if m and _fmt_no(m)[0] in CATALOG:
        no, sub = _fmt_no(m)
        return no, sub, "파일명"
    for _, attrs, _ in d.inserts_attribs:
        for tag, val in attrs.items():
            if any(t in _tagkey(tag) for t in _NO_TAGS):
                m = NO_RE.search(normalize(val))
                if m and _fmt_no(m)[0] in CATALOG:
                    no, sub = _fmt_no(m)
                    return no, sub, "표제란"
    exact = Counter()
    for t in d.texts:
        m = NO_RE.fullmatch(t.norm)
        if m and _fmt_no(m)[0] in CATALOG:
            exact[_fmt_no(m)] += 1
    if exact:
        (no, sub), _ = exact.most_common(1)[0]
        return no, sub, "도면 문자"
    return None, None, ""


def detect_title(d: Drawing) -> str:
    for _, attrs, _ in d.inserts_attribs:
        for tag, val in attrs.items():
            if any(t in _tagkey(tag) for t in _TITLE_TAGS) and val:
                return val
    return ""


# ── 사실 추출 ───────────────────────────────────────────────────────────
_N = r"(\d[\d,]*(?:\.\d+)?)"
_INV = re.compile(r"인버터|(?<![A-Z])INV|(?<![A-Z])PCS")
_MOD = re.compile(r"모듈|MODULE")
RX = {
    "capacity_kw": re.compile(r"(?:용량|발전량|CAPACITY)\s*[:=]?\s*" + _N + r"\s*KWP?(?![A-Z])|" + _N + r"\s*KWP(?![A-Z])"),
    "inverter_kw": re.compile(_N + r"\s*KW(?![A-Z])"),
    "module_count": re.compile(_N + r"\s*(?:장|매|EA|개)(?![A-Z])"),
    "module_w": re.compile(r"(?<![\d.])(\d{3,4})\s*WP?(?![A-Z])"),
    "inverter_count": re.compile(r"(?<![\d.])(\d+)\s*(?:대|EA|SET|UNIT)(?![A-Z])"),
    "series_parallel": re.compile(r"(?<![\d.])(\d+)\s*(?:직렬|S)\s*X?\s*(\d+)\s*(?:병렬|P)(?![A-Z0-9])"),
    "dc_fuse_a": re.compile(r"(?:퓨즈|FUSE|GPV)\s*[:=]?\s*" + _N + r"\s*AT?(?![A-Z])|(?<![\d.])" + _N + r"\s*AT?\s*(?:퓨즈|FUSE)"),
    "mppt": re.compile(r"MPPT\s*(?:채널)?\s*(?:수|개수)\s*[:=]?\s*(\d+)|(?<![\d.])(\d+)\s*MPPT"),
    "mppt_channel": re.compile(r"MPPT\s*-?\s*(\d+)\s*[:：]"),
    "string_vmax": re.compile(r"스트링\s*(?:최대\s*)?전압\s*[:=]?\s*" + _N + r"\s*V(?![A-Z])"),
    "inverter_vmax": re.compile(r"최대\s*입력\s*전압\s*[:=]?\s*" + _N + r"\s*V(?![A-Z])"),
}
_ENUMS = {
    "install_type": (("지상형", "지상형"), ("지붕형", "지붕형"), ("슬라브", "슬라브")),
    "tray_type": (("래더", "래더"), ("타공", "타공"), ("솔리드", "솔리드")),
}
PRESENCE = {
    "whm": re.compile(r"WHM|전력량계|계량기"),
    "pen": re.compile(r"(?<![A-Z])PEN(?![A-Z])"),
    "pe": re.compile(r"보호\s*접지|외함\s*접지|(?<![A-Z])PE(?![A-Z])"),
    "bonding": re.compile(r"본딩|BONDING"),
    "clamp": re.compile(r"클램프|CLAMP"),
    "polarity": re.compile(r"^\(?[+\-−]\)?$|양극|음극|\(\+\)|\(-\)"),
    "spacing": re.compile(r"간격\s*[:=]?\s*\d|@\s*\d"),
    "thickness": re.compile(r"(?<![A-Z])T\s*=\s*\d|두께"),
    "bolt": re.compile(r"(?<![A-Z])M\d{1,2}(?!\d)|볼트|BOLT"),
    "ground_caption": re.compile(r"(?:TFR-GV|F-GV|GV)\s*\d+(?:\.\d+)?\s*SQ"),
    "mppt_word": re.compile(r"MPPT"),
    "string_word": re.compile(r"스트링|STRING"),
    "inverter_word": _INV,
    "outline_block": re.compile(r"외형|OUTLINE"),
}
_MM2_RAW = re.compile(r"mm\s*[²2]", re.I)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


@dataclass
class Sheet:
    arcname: str
    no: Optional[str]
    sub: Optional[int]
    source: str
    title: str
    drawing: Drawing
    elec: ElectricalModel
    facts: Dict[str, List[Tuple[object, TextItem]]] = field(default_factory=dict)
    present: Dict[str, int] = field(default_factory=dict)
    mm2_raw: List[TextItem] = field(default_factory=list)
    corpus: str = ""

    def value(self, fact: str):
        """도면 안에서 가장 많이 나온 값."""
        vals = self.facts.get(fact)
        if not vals:
            return None
        return Counter(v for v, _ in vals).most_common(1)[0][0]

    def where(self, fact: str) -> Optional[TextItem]:
        vals = self.facts.get(fact)
        return vals[0][1] if vals else None


def extract_facts(sheet: Sheet, settings: Settings) -> None:
    f: Dict[str, List[Tuple[object, TextItem]]] = {}

    def add(k, v, t):
        f.setdefault(k, []).append((v, t))

    for t in sheet.drawing.texts:
        n = t.norm
        inv, mod = bool(_INV.search(n)), bool(_MOD.search(n))
        if not inv:
            for m in RX["capacity_kw"].finditer(n):
                add("capacity_kw", _num(m.group(1) or m.group(2)), t)
        else:
            for m in RX["inverter_kw"].finditer(n):
                add("inverter_kw", _num(m.group(1)), t)
            for m in RX["inverter_count"].finditer(n):
                add("inverter_count", int(m.group(1)), t)
        if mod:
            for m in RX["module_count"].finditer(n):
                add("module_count", int(_num(m.group(1))), t)
            for m in RX["module_w"].finditer(n):
                add("module_w", int(m.group(1)), t)
        for m in RX["series_parallel"].finditer(n):
            add("series", int(m.group(1)), t)
            add("parallel", int(m.group(2)), t)
        for m in RX["dc_fuse_a"].finditer(n):
            add("dc_fuse_a", _num(m.group(1) or m.group(2)), t)
        for m in RX["mppt"].finditer(n):
            add("mppt", int(m.group(1) or m.group(2)), t)
        for m in RX["mppt_channel"].finditer(n):
            add("mppt_channel", int(m.group(1)), t)
        for m in RX["string_vmax"].finditer(n):
            add("string_vmax", _num(m.group(1)), t)
        for m in RX["inverter_vmax"].finditer(n):
            add("inverter_vmax", _num(m.group(1)), t)
        if ("수전" in n or "연계" in n or "인입" in n):
            if "특고압" in n or "고압" in n or "22.9KV" in n:
                add("receiving", "고압", t)
            elif "저압" in n:
                add("receiving", "저압", t)
        for key, opts in _ENUMS.items():
            for word, val in opts:
                if word in n:
                    add(key, val, t)
        for key, rx in PRESENCE.items():
            if rx.search(n):
                sheet.present[key] = sheet.present.get(key, 0) + 1
        if _MM2_RAW.search(t.text) and "㎟" not in t.text:
            sheet.mm2_raw.append(t)

    # 전선 규격: DC(문자에 DC 또는 PV 전용 케이블) / AC
    for a in sheet.elec.annotations:
        is_dc = "DC" in a.item.norm or any(c.type in ("H1Z2Z2-K", "PV") for c in a.cables)
        for c in a.cables:
            add("dc_sq" if is_dc else "ac_sq", c.size, a.item)
    for b, t in sheet.elec.breakers:
        if b.at is not None and b.kind != "FUSE":
            add("mccb_at", b.at, t)
        if b.af is not None:
            add("mccb_af", b.af, t)
        if b.kind == "FUSE" and b.at is not None:
            add("dc_fuse_a", b.at, t)
    sheet.facts = f
    parts = [corpus_key(t.text) for t in sheet.drawing.texts]
    for _, attrs, _ in sheet.drawing.inserts_attribs:
        parts.extend(corpus_key(v) for v in attrs.values())
    sheet.corpus = "\n".join(parts)


def build_sheet(arcname: str, d: Drawing, elec: ElectricalModel, settings: Settings) -> Sheet:
    no, sub, src = detect_number(arcname, d)
    s = Sheet(arcname=arcname, no=no, sub=sub, source=src, title=detect_title(d), drawing=d, elec=elec)
    extract_facts(s, settings)
    return s


def metadata_facts(sheets: List[Sheet], settings: Settings) -> Dict[str, object]:
    """세트 전체 XRECORD 메타데이터를 표준 사실명으로 바꾼다."""
    merged: Dict[str, object] = {}
    for s in sheets:
        for k, v in s.drawing.metadata.items():
            merged.setdefault(k, v)
    out: Dict[str, object] = {}
    for fact, keys in settings.meta_keys.items():
        for k in keys:
            if k in merged and merged[k] not in (None, ""):
                out[fact] = merged[k]
                break
    return out
