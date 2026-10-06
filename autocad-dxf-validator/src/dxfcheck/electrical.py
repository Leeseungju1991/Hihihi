"""도면 문자에서 전기 설비 표기를 읽어 회로(차단기 ↔ 전선)로 묶는다.

인식 예:
  전선   F-CV 4C 25SQ · 0.6/1kV F-CV 4C-25㎟ · CV 1C 95SQ×4 · 2(CV 1C 240SQ×4) · HFIX 2.5SQ-3
  보호도체 +E 16SQ · F-GV 6㎟ · 접지선 GV 16SQ
  차단기 MCCB 3P 100AF 75AT 25kA · ELB 2P 30AF 20AT 30mA · MCB 1P 20A · 누전차단기 2P 30AT 15mA
  부가정보 L=45m · IB=32A · 15kW · 380V · 3Φ4W · 조명/콘센트/욕실/동력
"""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Set, Tuple

from . import kec
from .config import Settings
from .drawing import Drawing, TextItem

# ── 정규식 ──────────────────────────────────────────────────────────────
_TYPE_ALT = "|".join(re.escape(k) for k in sorted(kec.CABLE_TYPES, key=len, reverse=True))
_NUM = r"\d+(?:\.\d+)?"

CABLE_RE = re.compile(
    r"(?:(?P<par1>\d+)\s*\(\s*)?"
    r"(?<![A-Z0-9-])(?P<type>" + _TYPE_ALT + r")(?![A-Z])"
    r"\s*(?:0\.6/1\s*KV\s*)?(?:" + _NUM + r"\s*KV\s*)?"
    r"(?:(?P<cores>\d+)\s*C\b\s*[-X/,]?\s*)?"
    r"(?P<size>" + _NUM + r")\s*SQ"
    r"(?:\s*[/-]\s*(?P<cores2>\d+)\s*C\b)?"
    r"(?:\s*[X-]\s*(?P<count>\d+)(?![\d.]*\s*(?:SQ|C\b|M\b)))?"
    r"(?:\s*\)\s*X\s*(?P<par2>\d+))?"
)
PE_RE = re.compile(
    r"(?:(?<![A-Z0-9-])(?P<k>TFR-GV|F-GV|GV|PE|E)(?![A-Z])|(?P<kr>접지\s*(?:선|도체|극)?|보호\s*도체))"
    r"\s*[:(]?\s*(?:F-GV|GV)?\s*(?P<size>" + _NUM + r")\s*SQ\)?"
)
BARE_SIZE_RE = re.compile(r"(?<![\d.A-Z])(?P<size>" + _NUM + r")\s*SQ(?:\s*[X-]\s*(?P<count>\d+)(?![\d.]*\s*SQ))?")

KIND_RE = re.compile(
    r"(?<![A-Z])(MCCB|ELCB|ELB|RCBO|RCCB|MCB|ACB|VCB|NFB|FUSE|CB)(?![A-Z])"
    r"|(누전\s*차단기|배선용\s*차단기|차단기|퓨즈)"
)
_KIND_MAP = {"ELCB": "ELB", "NFB": "MCCB", "누전차단기": "ELB", "배선용차단기": "MCCB", "차단기": "CB", "퓨즈": "FUSE"}
AF_RE = re.compile(r"(?<![\d.])(\d+)\s*AF(?![A-Z])")
AT_RE = re.compile(r"(?<![\d.])(" + _NUM + r")\s*AT(?![A-Z])")
A_RE = re.compile(r"(?<![\d.])(" + _NUM + r")\s*A(?![A-Z])")
MA_RE = re.compile(r"(?<![\d.])(\d+)\s*MA(?![A-Z])")
KA_RE = re.compile(r"(?<![\d.])(" + _NUM + r")\s*KA(?![A-Z])")
POLE_RE = re.compile(r"(?<![\d.])([1-4])\s*P(?![A-Z0-9])")

LEN_RE = re.compile(r"(?:(?<![A-Z])L|길이|거리|긍장)\s*[=:]\s*(" + _NUM + r")\s*M(?![A-Z])")
IB_RE = re.compile(r"(?:(?<![A-Z])IB|(?<![A-Z])IL|부하\s*전류|설계\s*전류|(?<![A-Z])I)\s*[=:]\s*(" + _NUM + r")\s*A(?![A-Z])")
KW_RE = re.compile(r"(?<![\d.])(" + _NUM + r")\s*(KW|KVA)(?![A-Z])")
W_RE = re.compile(r"(?<![\d.Φ])(\d{2,6})\s*W(?![A-Z])")
V_RE = re.compile(r"(?<![\d.])(\d{3})(?:\s*/\s*(\d{3}))?\s*V(?![A-Z])")
KV_RE = re.compile(r"(?<![\d.])(" + _NUM + r")\s*KV(?![A-Z])")
WIRING_RE = re.compile(r"(?<!\d)([13])\s*(?:Φ|P)\s*([234])\s*W(?![A-Z])")
PHASE_RE = re.compile(r"(?<!\d)([13])\s*Φ")

PURPOSES = {
    "lighting": ("조명", "전등", "등기구", "LIGHT", "비상등", "유도등", "가로등"),
    "outlet": ("콘센트", "전열", "RECEPT", "OUTLET", "CONSENT"),
    "bath": ("욕실", "화장실", "샤워", "욕조", "BATH", "TOILET"),
    "outdoor": ("옥외", "실외", "외부", "가로등", "수영장", "풀장", "OUTDOOR"),
    "motor": ("동력", "모터", "MOTOR", "펌프", "PUMP", "FAN", "팬", "승강기", "엘리베이터", "E/V"),
    "control": ("제어", "신호", "표시", "CONTROL", "통신", "감시"),
    "lps": ("피뢰",),
    "underground": ("지중", "매설"),
    "ground": ("접지",),
}


# ── 모델 ────────────────────────────────────────────────────────────────
@dataclass
class Cable:
    raw: str
    size: float
    type: Optional[str] = None
    cores: Optional[int] = None
    count: Optional[int] = None
    parallel: int = 1
    parallel_guessed: bool = False
    llm: bool = False          # 규칙이 못 읽어 LLM 해석으로 얻은 값

    @property
    def insulation(self) -> str:
        return kec.CABLE_TYPES.get(self.type or "", ("PVC", False, True))[0]

    @property
    def is_wire(self) -> bool:
        if self.type is None:
            return True
        return kec.CABLE_TYPES[self.type][1]

    @property
    def low_voltage(self) -> bool:
        if self.type is None:
            return True
        return kec.CABLE_TYPES[self.type][2]

    @property
    def is_control(self) -> bool:
        return self.type in kec.CONTROL_CABLES

    def label(self) -> str:
        return self.raw


@dataclass
class PEConductor:
    raw: str
    size: float
    grounding: bool   # 접지도체(접지극 연결) 여부. False면 회로 보호도체
    llm: bool = False


@dataclass
class Breaker:
    raw: str
    kind: Optional[str] = None
    poles: Optional[int] = None
    af: Optional[float] = None
    at: Optional[float] = None
    ma: Optional[float] = None
    ka: Optional[float] = None
    llm: bool = False

    @property
    def residual(self) -> bool:
        return self.kind in ("ELB", "RCBO", "RCCB") or self.ma is not None

    @property
    def overload(self) -> bool:
        """과부하 보호 장치인가 (RCCB·VCB는 과부하 판정 제외)."""
        return self.kind not in ("RCCB", "VCB") and self.at is not None

    def label(self) -> str:
        return self.raw


@dataclass
class Annotation:
    item: TextItem
    cables: List[Cable] = field(default_factory=list)
    pes: List[PEConductor] = field(default_factory=list)
    breakers: List[Breaker] = field(default_factory=list)
    purposes: Set[str] = field(default_factory=set)
    length_m: Optional[float] = None
    ib: Optional[float] = None
    kw: Optional[float] = None
    kva: Optional[float] = None
    voltage: Optional[float] = None
    wiring: Optional[str] = None   # 1P2W, 1P3W, 3P3W, 3P4W
    phase: Optional[int] = None

    @property
    def has_electrical(self) -> bool:
        return bool(self.cables or self.pes or self.breakers)

    @property
    def has_context(self) -> bool:
        return bool(self.purposes or self.length_m or self.ib or self.kw or self.kva
                    or self.voltage or self.wiring)


@dataclass
class Circuit:
    breaker: Breaker
    cable: Cable
    anchor: TextItem
    basis: str                       # 같은 문자 / 같은 행 / 근접
    pe: Optional[PEConductor] = None
    purposes: Set[str] = field(default_factory=set)
    length_m: Optional[float] = None
    ib: Optional[float] = None
    kw: Optional[float] = None
    kva: Optional[float] = None
    voltage: Optional[float] = None
    wiring: Optional[str] = None
    phase: Optional[int] = None
    texts: List[str] = field(default_factory=list)
    cable_item: Optional[TextItem] = None   # 전선 규격이 적힌 문자 (재설계 수정 대상)
    pe_item: Optional[TextItem] = None

    @property
    def llm(self) -> bool:
        return self.breaker.llm or self.cable.llm or bool(self.pe and self.pe.llm)


@dataclass
class ElectricalModel:
    annotations: List[Annotation] = field(default_factory=list)
    circuits: List[Circuit] = field(default_factory=list)
    unmatched_breakers: List[Tuple[Breaker, TextItem]] = field(default_factory=list)
    default_voltage: Optional[float] = None
    default_wiring: Optional[str] = None

    @property
    def cables(self) -> List[Tuple[Cable, TextItem]]:
        return [(c, a.item) for a in self.annotations for c in a.cables]

    @property
    def breakers(self) -> List[Tuple[Breaker, TextItem]]:
        return [(b, a.item) for a in self.annotations for b in a.breakers]

    @property
    def pes(self) -> List[Tuple[PEConductor, TextItem, bool]]:
        """(도체, 문자, 같은 문자에 상도체가 있는지)."""
        return [(p, a.item, bool(a.cables)) for a in self.annotations for p in a.pes]

    @property
    def is_electrical(self) -> bool:
        return any(a.cables or a.breakers for a in self.annotations)


# ── 파서 ────────────────────────────────────────────────────────────────
def _mask(s: str, spans: Iterable[Tuple[int, int]]) -> str:
    chars = list(s)
    for a, b in spans:
        for i in range(a, b):
            chars[i] = " "
    return "".join(chars)


def parse_cables(norm: str) -> Tuple[List[Cable], List[PEConductor]]:
    pes: List[PEConductor] = []
    spans: List[Tuple[int, int]] = []
    for m in PE_RE.finditer(norm):
        kr = m.group("kr") or ""
        grounding = kr.startswith("접지") or "접지도체" in norm or "접지선" in norm or "GROUND" in norm
        pes.append(PEConductor(raw=m.group(0).strip(), size=float(m.group("size")), grounding=grounding))
        spans.append(m.span())
    rest = _mask(norm, spans)

    cables: List[Cable] = []
    spans = []
    for m in CABLE_RE.finditer(rest):
        cores = m.group("cores") or m.group("cores2")
        count = m.group("count")
        par = m.group("par1") or m.group("par2")
        c = Cable(raw=m.group(0).strip(), size=float(m.group("size")), type=m.group("type"),
                  cores=int(cores) if cores else None, count=int(count) if count else None)
        _set_parallel(c, int(par) if par else None)
        cables.append(c)
        spans.append(m.span())
    rest = _mask(rest, spans)
    for m in BARE_SIZE_RE.finditer(rest):
        count = m.group("count")
        c = Cable(raw=m.group(0).strip(), size=float(m.group("size")), count=int(count) if count else None)
        _set_parallel(c, None)
        cables.append(c)
    return cables, pes


def _set_parallel(c: Cable, explicit: Optional[int]) -> None:
    if explicit:
        c.parallel = explicit
        return
    if c.count and c.cores and c.cores > 1:
        c.parallel = c.count          # 다심 케이블 ×N = N조 병렬
    elif c.count and c.count > 4:     # 단심/절연전선 ×8 → 4선 2조로 추정
        for per in (4, 3):
            if c.count % per == 0:
                c.parallel = c.count // per
                c.parallel_guessed = True
                break


def parse_breakers(norm: str) -> List[Breaker]:
    matches = list(KIND_RE.finditer(norm))
    segments: List[Tuple[Optional[str], str]] = []
    if matches:
        head = norm[: matches[0].start()]
        if AT_RE.search(head) or AF_RE.search(head):
            segments.append((None, head))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(norm)
            kind = (m.group(1) or m.group(2) or "").replace(" ", "")
            segments.append((_KIND_MAP.get(kind, kind), norm[m.start(): end]))
    elif AT_RE.search(norm) or AF_RE.search(norm):
        segments.append((None, norm))

    out: List[Breaker] = []
    for kind, seg in segments:
        b = Breaker(raw=seg.strip(" ,/;"), kind=kind)
        m = AF_RE.search(seg)
        b.af = float(m.group(1)) if m else None
        m = AT_RE.search(seg)
        if m:
            b.at = float(m.group(1))
        elif kind:
            for m in A_RE.finditer(seg):
                v = float(m.group(1))
                if b.af is None or v != b.af:
                    b.at = v
                    break
        m = MA_RE.search(seg)
        b.ma = float(m.group(1)) if m else None
        m = KA_RE.search(seg)
        b.ka = float(m.group(1)) if m else None
        m = POLE_RE.search(seg)
        b.poles = int(m.group(1)) if m else None
        if b.at is None and b.af is None and b.ma is None:
            continue   # '차단기' 단어만 있는 설명문
        if b.kind is None and b.ma is not None:
            b.kind = "ELB"
        out.append(b)
    return out


def parse_annotation(item: TextItem) -> Annotation:
    n = item.norm
    a = Annotation(item=item)
    a.cables, a.pes = parse_cables(n)
    a.breakers = parse_breakers(n)
    for key, words in PURPOSES.items():
        if any(w in n for w in words):
            a.purposes.add(key)
    m = LEN_RE.search(n)
    a.length_m = float(m.group(1)) if m else None
    m = IB_RE.search(n)
    a.ib = float(m.group(1)) if m else None
    for m in KW_RE.finditer(n):
        if m.group(2) == "KW":
            a.kw = float(m.group(1))
        else:
            a.kva = float(m.group(1))
    if a.kw is None and a.kva is None:
        m = W_RE.search(n)
        if m and not a.cables:
            a.kw = float(m.group(1)) / 1000.0
    m = V_RE.search(n)
    if m:
        a.voltage = float(m.group(1))
        if m.group(2):
            a.voltage = max(float(m.group(1)), float(m.group(2)))
            a.wiring = a.wiring or "3P4W"
    m = WIRING_RE.search(n)
    if m:
        a.wiring = "%sP%sW" % (m.group(1), m.group(2))
        a.phase = int(m.group(1))
    else:
        m = PHASE_RE.search(n)
        if m:
            a.phase = int(m.group(1))
    if a.wiring and a.phase is None:
        a.phase = int(a.wiring[0])
    # 저압 = 교류 1kV 이하. '0.6/1kV'는 저압 케이블 정격 표기이므로 제외한다.
    m = KV_RE.search(re.sub(r"0\.6\s*/\s*1\s*KV", "", n))
    if m and float(m.group(1)) > 1.0:
        a.purposes.add("hv")
    return a


# ── 연관 (차단기 ↔ 전선) ─────────────────────────────────────────────────
def _dist(a: TextItem, b: TextItem, s: Settings) -> Tuple[Optional[str], float]:
    if a.layout != b.layout:
        return None, math.inf
    h = max(a.h, b.h, 1e-6)
    dx, dy = abs(a.x - b.x), abs(a.y - b.y)
    if dy <= s.row_tolerance * h and dx <= s.row_max_distance * h:
        return "같은 행", dx / h
    d = math.hypot(dx, dy) / h
    if d <= s.near_radius:
        return "근접", 1000.0 + d   # 같은 행 후보를 먼저 채운다
    return None, math.inf


def parse_all(drawing: Drawing) -> List[Annotation]:
    """모든 문자를 규칙으로 해석한다(문자 하나당 Annotation 하나, 비어 있어도 포함)."""
    return [parse_annotation(t) for t in drawing.texts]


def build(drawing: Drawing, settings: Settings, annotations: Optional[List[Annotation]] = None) -> ElectricalModel:
    em = ElectricalModel()
    for a in (annotations if annotations is not None else parse_all(drawing)):
        if a.has_electrical or a.has_context:
            em.annotations.append(a)

    volts = Counter(a.voltage for a in em.annotations if a.voltage and "hv" not in a.purposes)
    wirings = Counter(a.wiring for a in em.annotations if a.wiring)
    em.default_voltage = volts.most_common(1)[0][0] if volts else None
    em.default_wiring = wirings.most_common(1)[0][0] if wirings else None

    used_cable_annots: Set[int] = set()
    pending: List[Tuple[Breaker, Annotation]] = []
    for idx, a in enumerate(em.annotations):
        if not a.breakers:
            continue
        phase_cables = [c for c in a.cables]
        if phase_cables and len(a.breakers) == 1:
            em.circuits.append(_circuit(a.breakers[0], phase_cables[0], a, None, "같은 문자"))
            used_cable_annots.add(idx)
        elif phase_cables and len(phase_cables) == len(a.breakers):
            for b, c in zip(a.breakers, phase_cables):
                em.circuits.append(_circuit(b, c, a, None, "같은 문자"))
            used_cable_annots.add(idx)
        else:
            for b in a.breakers:
                pending.append((b, a))

    candidates = [(i, a) for i, a in enumerate(em.annotations)
                  if a.cables and not a.breakers and i not in used_cable_annots]
    pairs = []
    for bi, (b, ba) in enumerate(pending):
        for ci, ca in candidates:
            basis, score = _dist(ba.item, ca.item, settings)
            if basis:
                pairs.append((score, bi, ci, basis))
    pairs.sort()
    taken_b: Set[int] = set()
    taken_c: Set[int] = set()
    for score, bi, ci, basis in pairs:
        if bi in taken_b or ci in taken_c:
            continue
        taken_b.add(bi)
        taken_c.add(ci)
        b, ba = pending[bi]
        ca = em.annotations[ci]
        em.circuits.append(_circuit(b, ca.cables[0], ba, ca, basis))
    for bi, (b, ba) in enumerate(pending):
        if bi not in taken_b:
            em.unmatched_breakers.append((b, ba.item))

    # 같은 행의 부가정보(용도·길이·부하) 흡수
    ctx_only = [a for a in em.annotations if a.has_context and not a.cables and not a.breakers]
    for c in em.circuits:
        for a in ctx_only:
            basis, _ = _dist(c.anchor, a.item, settings)
            if basis == "같은 행":
                _merge_ctx(c, a)
        if c.voltage is None:
            c.voltage = em.default_voltage
        if c.wiring is None and c.phase is None:
            c.wiring = em.default_wiring if c.breaker.poles is None else None
        if c.phase is None and c.wiring:
            c.phase = int(c.wiring[0])
    return em


def _merge_ctx(c: Circuit, a: Annotation) -> None:
    c.purposes |= a.purposes
    c.length_m = c.length_m or a.length_m
    c.ib = c.ib or a.ib
    c.kw = c.kw or a.kw
    c.kva = c.kva or a.kva
    c.voltage = c.voltage or a.voltage
    c.wiring = c.wiring or a.wiring
    c.phase = c.phase or a.phase
    if a.item.text not in c.texts:
        c.texts.append(a.item.text)
    if c.pe is None and a.pes:
        c.pe = a.pes[0]


def _circuit(b: Breaker, cable: Cable, ba: Annotation, ca: Optional[Annotation], basis: str) -> Circuit:
    c = Circuit(breaker=b, cable=cable, anchor=ba.item, basis=basis, texts=[ba.item.text])
    _merge_ctx(c, ba)
    if ca is not None:
        _merge_ctx(c, ca)
    pes = (ca.pes if ca is not None else []) or ba.pes
    c.pe = pes[0] if pes else None
    c.cable_item = ca.item if ca is not None else ba.item
    c.pe_item = (ca.item if ca is not None and ca.pes else ba.item) if c.pe else None
    return c
