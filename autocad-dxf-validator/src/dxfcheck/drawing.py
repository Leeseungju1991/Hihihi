"""DXF 읽기와 검증용 도면 모델 추출.

규칙은 ezdxf 문서를 직접 만지지 않고 이 모듈이 만든 `Drawing`만 본다.
"""
from __future__ import annotations

import json
import math
import re
import zlib
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import ezdxf
from ezdxf import bbox, recover
from ezdxf.lldxf.const import DXFStructureError

from .config import Settings

_PHI = re.compile("[ΦφϕɸØø∅Ф]")
_MUL = re.compile("[×✕✖*]")
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """전기 표기 비교용 정규화: NFKC(㎟→mm2, ²→2) · 대문자 · Φ/× 통일 · 공백 축소."""
    t = unicodedata.normalize("NFKC", text)
    t = _PHI.sub("Φ", t).upper()
    t = _MUL.sub("X", t)
    t = t.replace("MM2", "SQ").replace("SQ.", "SQ")
    return _SPACES.sub(" ", t).strip()


@dataclass
class TextItem:
    text: str
    norm: str
    x: float
    y: float
    h: float
    layer: str
    layout: str
    handle: str
    kind: str          # TEXT, MTEXT, ATTRIB, BLOCK-TEXT, BLOCK-MTEXT
    style: str = ""
    block: str = ""    # 블록 안 문자면 블록 이름


@dataclass
class LayerInfo:
    name: str
    color: int
    linetype: str
    off: bool
    frozen: bool
    locked: bool
    plot: bool


@dataclass
class Drawing:
    path: Path
    dxfversion: str = ""
    release: str = ""
    insunits: int = 0
    measurement: int = 0
    layers: Dict[str, LayerInfo] = field(default_factory=dict)
    styles: Dict[str, Tuple[str, str]] = field(default_factory=dict)  # 이름 → (font, bigfont)
    texts: List[TextItem] = field(default_factory=list)
    entity_count: Counter = field(default_factory=Counter)        # 유형별 (모든 배치)
    layer_count: Counter = field(default_factory=Counter)         # 레이어별 (모든 배치)
    layout_count: Counter = field(default_factory=Counter)
    blocks_used: Counter = field(default_factory=Counter)
    inserts_attribs: List[Tuple[str, Dict[str, str], str]] = field(default_factory=list)  # (블록, 속성, handle)
    xrefs: List[Tuple[str, str]] = field(default_factory=list)   # (블록 이름, 경로)
    images: List[str] = field(default_factory=list)              # IMAGEDEF 파일 경로
    proxies: int = 0
    non_bylayer_color: int = 0
    zero_length: List[Tuple[str, str]] = field(default_factory=list)   # (handle, layer)
    duplicate_lines: List[Tuple[str, str]] = field(default_factory=list)
    dim_overrides: List[Tuple[str, str, str]] = field(default_factory=list)  # (handle, layer, text)
    defpoints_objects: int = 0
    hidden_layer_objects: Counter = field(default_factory=Counter)
    extents: Optional[Tuple[Tuple[float, float], Tuple[float, float]]] = None
    audit_errors: List[str] = field(default_factory=list)
    audit_fixes: int = 0
    load_error: str = ""
    # 설계 메타데이터 (XRECORD 안의 JSON) — SolarAutoDesign 설계 조건
    metadata: Dict[str, object] = field(default_factory=dict)
    nonuniform_inserts: List[Tuple[str, float, float, str]] = field(default_factory=list)  # (블록, sx, sy, handle)
    paper_layouts: List[Tuple[str, float, float]] = field(default_factory=list)  # (배치, 용지 폭, 높이 mm)

    @property
    def total_entities(self) -> int:
        return sum(self.entity_count.values())

    @property
    def model_entities(self) -> int:
        return self.layout_count.get("Model", 0)


_INSUNITS_MM = {1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0, 14: 100.0}
INSUNITS_NAME = {0: "미지정", 1: "inch", 2: "feet", 4: "mm", 5: "cm", 6: "m", 14: "dm"}


def unit_to_mm(insunits: int) -> Optional[float]:
    return _INSUNITS_MM.get(insunits)


def is_dwg(path: Path) -> bool:
    """DWG 이진 서명(AC1015 등)인지 본다. DXF 이진 형식은 'AutoCAD Binary DXF'로 시작한다."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(6)
    except OSError:
        return False
    return head[:2] == b"AC" and head[2:6].isdigit()


def load(path: Path, settings: Settings) -> Drawing:
    d = Drawing(path=path)
    try:
        doc, auditor = recover.readfile(str(path))
    except (IOError, OSError) as exc:
        d.load_error = "파일을 읽을 수 없습니다: %s" % exc
        return d
    except DXFStructureError as exc:
        d.load_error = "DXF 구조가 손상되어 복구할 수 없습니다: %s" % exc
        return d
    except Exception as exc:  # noqa: BLE001  (ezdxf 내부 예외 다양)
        d.load_error = "DXF 해석 실패: %s" % exc
        return d

    d.audit_errors = ["[%s] %s" % (e.code, e.message) for e in auditor.errors]
    d.audit_fixes = len(auditor.fixes)
    d.dxfversion = doc.dxfversion
    d.release = ezdxf.const.acad_release.get(doc.dxfversion, "?")
    d.insunits = int(doc.header.get("$INSUNITS", 0) or 0)
    d.measurement = int(doc.header.get("$MEASUREMENT", 0) or 0)

    for layer in doc.layers:
        name = layer.dxf.name
        d.layers[name.upper()] = LayerInfo(
            name=name, color=abs(int(layer.dxf.get("color", 7))),
            linetype=layer.dxf.get("linetype", "Continuous"),
            off=layer.is_off(), frozen=layer.is_frozen(), locked=layer.is_locked(),
            plot=bool(layer.dxf.get("plot", 1)),
        )
    for st in doc.styles:
        d.styles[st.dxf.name.upper()] = (st.dxf.get("font", "") or "", st.dxf.get("bigfont", "") or "")

    for blk in doc.blocks:
        try:
            if blk.block is not None and blk.block.dxf.get("flags", 0) & 4:
                d.xrefs.append((blk.name, blk.block.dxf.get("xref_path", "")))
        except Exception:  # noqa: BLE001
            pass
    for obj in doc.objects.query("IMAGEDEF"):
        d.images.append(obj.dxf.get("filename", ""))

    d.metadata = read_metadata(doc)
    for name in doc.layouts.names_in_taborder():
        lay = doc.layouts.get(name)
        if lay.is_modelspace:
            continue
        try:
            dl = lay.dxf_layout.dxf
            d.paper_layouts.append((name, float(dl.get("paper_width", 0) or 0), float(dl.get("paper_height", 0) or 0)))
        except Exception:  # noqa: BLE001
            pass

    line_keys: Dict[tuple, str] = {}
    for layout_name in doc.layouts.names_in_taborder():
        layout = doc.layouts.get(layout_name)
        lname = "Model" if layout.is_modelspace else layout_name
        for e in layout:
            _visit(d, e, lname, line_keys, settings)

    try:
        ext = bbox.extents(doc.modelspace(), fast=True)
        if ext.has_data:
            d.extents = ((ext.extmin.x, ext.extmin.y), (ext.extmax.x, ext.extmax.y))
    except Exception:  # noqa: BLE001
        pass
    return d


def _layer(e) -> str:
    return e.dxf.get("layer", "0") or "0"


def _add_text(d: Drawing, e, layout: str, block: str = "", layer_override: str = "") -> None:
    t = e.dxftype()
    try:
        if t == "TEXT" or t == "ATTRIB":
            txt = e.plain_text()
            ins = e.dxf.get("insert")
            h = float(e.dxf.get("height", 0) or 0)
        elif t == "MTEXT":
            txt = e.plain_text()
            ins = e.dxf.get("insert")
            h = float(e.dxf.get("char_height", 0) or 0)
        else:
            return
    except Exception:  # noqa: BLE001
        return
    if not txt or not txt.strip() or ins is None:
        return
    kind = t if not block or t == "ATTRIB" else "BLOCK-" + t
    layer = _layer(e)
    if layer == "0" and layer_override:
        layer = layer_override
    d.texts.append(TextItem(
        text=txt.strip(), norm=normalize(txt), x=float(ins[0]), y=float(ins[1]), h=h,
        layer=layer, layout=layout, handle=e.dxf.get("handle", "") or "", kind=kind,
        style=(e.dxf.get("style", "Standard") or "Standard"), block=block,
    ))


def _visit(d: Drawing, e, layout: str, line_keys: Dict[tuple, str], settings: Settings) -> None:
    t = e.dxftype()
    layer = _layer(e)
    d.entity_count[t] += 1
    d.layer_count[layer.upper()] += 1
    d.layout_count[layout] += 1
    info = d.layers.get(layer.upper())
    if info and (info.off or info.frozen):
        d.hidden_layer_objects[info.name] += 1
    if layer.upper() == "DEFPOINTS" and t not in ("POINT", "DIMENSION", "VIEWPORT"):
        d.defpoints_objects += 1
    if t in ("ACAD_PROXY_ENTITY",) or e.__class__.__name__ == "UnknownEntity":
        d.proxies += 1
    color = e.dxf.get("color", 256)
    if color not in (256, None) and t not in ("VIEWPORT",):
        d.non_bylayer_color += 1

    if t in ("TEXT", "MTEXT"):
        _add_text(d, e, layout)
    elif t == "LINE":
        s, en = e.dxf.start, e.dxf.end
        handle = e.dxf.get("handle", "")
        if math.dist((s.x, s.y, s.z), (en.x, en.y, en.z)) < 1e-9:
            d.zero_length.append((handle, layer))
        else:
            a = (round(s.x, 6), round(s.y, 6), round(s.z, 6))
            b = (round(en.x, 6), round(en.y, 6), round(en.z, 6))
            key = (layout, min(a, b), max(a, b))
            if key in line_keys:
                d.duplicate_lines.append((handle, layer))
            else:
                line_keys[key] = handle
    elif t == "DIMENSION":
        txt = e.dxf.get("text", "") or ""
        if txt not in ("", "<>"):
            d.dim_overrides.append((e.dxf.get("handle", ""), layer, txt))
    elif t == "INSERT":
        _visit_insert(d, e, layout, 0, settings)


def _visit_insert(d: Drawing, ins, layout: str, depth: int, settings: Settings) -> None:
    name = ins.dxf.get("name", "")
    d.blocks_used[name] += 1
    if depth == 0:
        sx, sy = abs(float(ins.dxf.get("xscale", 1) or 1)), abs(float(ins.dxf.get("yscale", 1) or 1))
        if abs(sx - sy) > 0.01 * max(sx, sy, 1e-9):
            d.nonuniform_inserts.append((name, sx, sy, ins.dxf.get("handle", "")))
    attrs: Dict[str, str] = {}
    for a in getattr(ins, "attribs", []):
        try:
            attrs[a.dxf.get("tag", "").upper()] = a.plain_text().strip()
        except Exception:  # noqa: BLE001
            continue
        _add_text(d, a, layout, block=name)
    if attrs:
        d.inserts_attribs.append((name, attrs, ins.dxf.get("handle", "")))
    if depth >= settings.max_block_depth:
        return
    try:
        virtuals = list(ins.virtual_entities())
    except Exception:  # noqa: BLE001  (비균일 축척 등)
        return
    for v in virtuals:
        vt = v.dxftype()
        if vt in ("TEXT", "MTEXT"):
            _add_text(d, v, layout, block=name, layer_override=_layer(ins))
        elif vt == "INSERT":
            _visit_insert(d, v, layout, depth + 1, settings)


# ── 설계 메타데이터 ─────────────────────────────────────────────────────
# [미검증 · 실제 SolarAutoDesign XRECORD 형식 확인 예정]
# XRECORD 의 문자열 태그(1·300·1000 등)를 이어 붙인 JSON, 또는 이진 태그(310)를 이어 붙인
# JSON / zlib 압축 JSON 을 읽는다. 중첩 키는 'a.b'와 말단 키 'b' 둘 다로 펼친다.
def _flatten(obj, prefix: str, out: Dict[str, object]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(v, "%s.%s" % (prefix, k) if prefix else str(k), out)
        return
    out[prefix] = obj
    leaf = prefix.rsplit(".", 1)[-1]
    out.setdefault(leaf, obj)


def _parse_blob(text: str) -> Optional[dict]:
    text = text.strip().lstrip("\ufeff")
    if not text.startswith("{"):
        return None
    try:
        v = json.loads(text)
    except ValueError:
        return None
    return v if isinstance(v, dict) else None


def read_metadata(doc) -> Dict[str, object]:
    out: Dict[str, object] = {}
    try:
        xrecords = list(doc.objects.query("XRECORD"))
    except Exception:  # noqa: BLE001
        return out
    for xr in xrecords:
        strings, blobs = [], []
        for tag in getattr(xr, "tags", []):
            v = tag.value
            if isinstance(v, (bytes, bytearray)):
                blobs.append(bytes(v))
            elif isinstance(v, str):
                strings.append(v)
        cands = ["".join(strings)] if strings else []
        if blobs:
            raw = b"".join(blobs)
            for data in (raw, None):
                try:
                    data = zlib.decompress(raw) if data is None else data
                    cands.append(data.decode("utf-8"))
                except Exception:  # noqa: BLE001
                    continue
        for c in cands:
            obj = _parse_blob(c)
            if obj:
                _flatten(obj, "", out)
    return out


# ── 문자 높이 · 축척 ───────────────────────────────────────────────────
_SCALE_LABELED = re.compile(r"(?:축척|SCALE|S)\s*[:=]?\s*(?:A[0-4]\s*)?1\s*[/:]\s*(\d{1,5})(?!\d)")
_SCALE_BARE = re.compile(r"^(?:A[0-4]\s*)?1\s*[/:]\s*(\d{1,5})$")


def detect_scale(d: Drawing) -> Optional[int]:
    """표제란 '축척 1/100' 등에서 대표 축척 분모를 찾는다."""
    found: Counter = Counter()
    for t in d.texts:
        m = _SCALE_LABELED.search(t.norm) or _SCALE_BARE.match(t.norm)
        if m:
            v = int(m.group(1))
            if 1 <= v <= 50000:
                found[v] += 1
    for _, attrs, _ in d.inserts_attribs:
        for tag, val in attrs.items():
            if "SCALE" in tag or "축척" in tag:
                m = _SCALE_BARE.match(normalize(val)) or _SCALE_LABELED.search(normalize(val))
                if m:
                    found[int(m.group(1))] += 3
    return found.most_common(1)[0][0] if found else None


def layers_by_count(d: Drawing) -> List[Tuple[str, int]]:
    return sorted(((d.layers[k].name if k in d.layers else k, n) for k, n in d.layer_count.items()),
                  key=lambda x: -x[1])


def group_texts_by_layout(d: Drawing) -> Dict[str, List[TextItem]]:
    out: Dict[str, List[TextItem]] = defaultdict(list)
    for t in d.texts:
        out[t.layout].append(t)
    return out
