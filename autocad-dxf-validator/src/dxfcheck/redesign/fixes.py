"""수정안(op)을 DXF 에 적용한다 — 문자·속성·헤더·스타일·엔티티 단위의 국소 수정만 한다.

도면 형상을 새로 그리는 일(페이지 추가, 직렬 수 재산정 등)은 `regenerate` op 로 남기고
도면 생성기(SolarAutoDesign)가 처리한다(redesign.loop 의 regenerator 훅).
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ezdxf import recover

UNITS: Dict[str, str] = {
    "size": r"(?=\s*(?:SQ|㎟|mm²|mm2|sq))",
    "ma": r"(?=\s*mA)",
    "af": r"(?=\s*AF)",
    "at": r"(?=\s*AT?(?![A-Z]))",
    "a": r"(?=\s*AT?(?![A-Z]))",
    "kw": r"(?=\s*kWp?)",
    "w": r"(?=\s*Wp?)",
    "ea": r"(?=\s*(?:장|매|EA|개))",
    "unit": r"(?=\s*(?:대|EA|SET|UNIT))",
    "series": r"(?=\s*(?:직렬|S))",
    "parallel": r"(?=\s*(?:병렬|P))",
    "plain": r"",
}


def fmt_num(v: float) -> str:
    return ("%g" % float(v))


def _num_pattern(old: float) -> str:
    v = float(old)
    if v == int(v):
        body = r"0*%d(?:\.0+)?" % int(v)
    else:
        body = re.escape(fmt_num(v)) + "0*"
    return r"(?<![\d.])" + body + r"(?![\d.])"


@dataclass
class Change:
    file: str
    op: str
    handle: str
    before: str
    after: str
    ok: bool
    detail: str = ""
    finding_id: str = ""
    rule_id: str = ""
    reason: str = ""
    confidence: str = ""     # rule / majority / memory / llm / generator
    reverted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def get_text(e) -> Optional[str]:
    t = e.dxftype()
    if t in ("TEXT", "ATTRIB", "ATTDEF"):
        return e.dxf.get("text", "")
    if t == "MTEXT":
        return e.text
    return None


def set_text(e, value: str) -> None:
    if e.dxftype() == "MTEXT":
        e.text = value
    else:
        e.dxf.text = value


def _text_op(e, op: dict) -> Tuple[bool, str, str, str]:
    before = get_text(e)
    if before is None:
        return False, "", "", "문자 객체가 아님(%s)" % e.dxftype()
    kind = op["op"]
    after = before
    if kind == "replace_number":
        pat = _num_pattern(op["old"]) + UNITS.get(op.get("unit", "plain"), "")
        after, n = re.subn(pat, fmt_num(op["new"]), before, count=1, flags=re.I)
        if not n:
            return False, before, before, "숫자 %s 를 찾지 못함" % fmt_num(op["old"])
    elif kind == "replace_text":
        if op["old"] in before:
            after = before.replace(op["old"], op["new"], 1)
        else:
            after, n = re.subn(re.escape(op["old"]), op["new"].replace("\\", "\\\\"), before, count=1, flags=re.I)
            if not n:
                return False, before, before, "'%s' 를 찾지 못함" % op["old"]
    elif kind == "replace_regex":
        flags = re.I if "i" in op.get("flags", "") else 0
        after, n = re.subn(op["pattern"], op["new"].replace("\\", "\\\\"), before, flags=flags)
        if not n:
            return False, before, before, "패턴 불일치"
    elif kind == "set_text":
        after = op["value"]
    set_text(e, after)
    return True, before, after, ""


def apply_ops(path: Path, ops: List[dict], meta: Dict[str, str]) -> List[Change]:
    """한 파일에 op 들을 적용하고 저장한다. meta: finding_id/rule_id/reason/confidence (op별 override 가능)."""
    doc, _ = recover.readfile(str(path))
    db = doc.entitydb
    out: List[Change] = []
    for op in ops:
        m = dict(meta, **op.get("_meta", {}))
        kind = op["op"]
        handle = str(op.get("handle", ""))
        ch = Change(file=op.get("file", ""), op=kind, handle=handle, before="", after="", ok=False,
                    finding_id=m.get("finding_id", ""), rule_id=m.get("rule_id", ""),
                    reason=m.get("reason", ""), confidence=m.get("confidence", ""))
        try:
            if kind in ("replace_number", "replace_text", "replace_regex", "set_text"):
                e = db.get(handle)
                if e is None or not e.is_alive:
                    ch.detail = "handle %s 없음" % handle
                else:
                    ch.ok, ch.before, ch.after, ch.detail = _text_op(e, op)
            elif kind == "set_attrib":
                ins = db.get(handle)
                hit = None
                for a in getattr(ins, "attribs", []) if ins is not None else []:
                    if a.dxf.get("tag", "").upper() == str(op["tag"]).upper():
                        hit = a
                        break
                if hit is None:
                    ch.detail = "속성 %s 없음" % op["tag"]
                else:
                    ch.before, ch.after = hit.dxf.get("text", ""), str(op["value"])
                    hit.dxf.text = ch.after
                    ch.ok = True
            elif kind == "set_header":
                ch.before = str(doc.header.get(op["var"], ""))
                doc.header[op["var"]] = op["value"]
                ch.after, ch.ok, ch.handle = str(op["value"]), True, op["var"]
            elif kind == "delete_entity":
                e = db.get(handle)
                if e is None or not e.is_alive:
                    ch.detail = "handle %s 없음" % handle
                else:
                    ch.before = e.dxftype()
                    lay = e.get_layout()
                    if lay is not None:
                        lay.delete_entity(e)
                    else:
                        db.delete_entity(e)
                    ch.after, ch.ok = "(삭제)", True
            elif kind == "set_style":
                st = doc.styles.get(op["style"])
                if st is None:
                    ch.detail = "스타일 %s 없음" % op["style"]
                else:
                    ch.before = st.dxf.get("bigfont", "")
                    st.dxf.bigfont = op["bigfont"]
                    ch.after, ch.ok, ch.handle = op["bigfont"], True, op["style"]
            else:
                ch.detail = "적용하지 않는 op: %s" % kind
        except Exception as exc:  # noqa: BLE001
            ch.detail = "적용 오류: %s" % exc
        out.append(ch)
    if any(c.ok for c in out):
        doc.saveas(str(path))
    return out
