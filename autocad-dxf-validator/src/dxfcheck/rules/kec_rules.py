"""KEC(한국전기설비규정) 전기 규칙.

판정 근거 수치는 `kec.py`에만 있다. 이 모듈은 도면 표기를 수치와 대조한다.
차단기와 전선이 같은 문자/같은 행에서 연관되면 '부적합', 근접 추정이면 '주의'로 낮춘다.
"""
from __future__ import annotations

import math
import re
from typing import Iterable, List, Optional, Tuple

from .. import kec
from ..electrical import Circuit
from ..model import Category, CircuitRow, Finding, Severity
from . import Context, loc, rule

K = Category.KEC


def _sev(basis: str) -> Severity:
    return Severity.ERROR if basis in ("같은 문자", "같은 행") else Severity.WARNING


def num_fix(item, old: float, new: float, unit: str, reason: str) -> dict:
    """문자(handle) 안의 숫자 old→new 교체 수정안. unit: size/ma/af/at/kw/plain (redesign.fixes.UNITS)."""
    if item is None or not item.handle or item.kind.startswith("BLOCK-"):
        return {}
    return {"ops": [{"op": "replace_number", "handle": item.handle, "old": old, "new": new, "unit": unit}],
            "reason": reason, "confidence": "rule"}


def _cap(ctx: Context, items: List[Finding]) -> List[Finding]:
    n = ctx.settings.max_findings_per_rule
    if len(items) <= n:
        return items
    head = items[:n]
    head.append(Finding(items[0].rule_id, K, Severity.INFO, "동일 지적 생략",
                        "같은 유형의 지적 %d건은 생략했습니다." % (len(items) - n), items[0].reference))
    return head


# ── 회로 조건 추정 ───────────────────────────────────────────────────────
def phase_of(c: Circuit) -> Tuple[int, bool]:
    """(상수, 추정 여부)."""
    if c.wiring:
        return int(c.wiring[0]), False
    if c.phase:
        return c.phase, False
    if c.breaker.poles:
        return (3 if c.breaker.poles >= 3 else 1), False
    cb = c.cable
    if cb.cores and cb.cores > 1:
        if cb.cores >= 4:
            return 3, False
        if cb.cores == 2:
            return 1, False
        return 3, True
    if cb.count:
        per = cb.count // max(1, cb.parallel)
        if per >= 4:
            return 3, False
        if per == 2:
            return 1, False
    if c.voltage:
        return (3 if c.voltage >= 300 else 1), True
    return 3, True


def wiring_of(c: Circuit, phase: int) -> str:
    if c.wiring:
        return c.wiring
    if phase == 1:
        return "1P2W"
    cb = c.cable
    if (cb.cores and cb.cores >= 4) or (cb.count and cb.count // max(1, cb.parallel) >= 4):
        return "3P4W"
    return "3P3W"


def iz_of(ctx: Context, c: Circuit, loaded: int) -> Optional[float]:
    cb = c.cable
    method = ctx.settings.wire_method if cb.is_wire else ctx.settings.cable_method
    base = kec.ampacity(cb.insulation, method, loaded, cb.size)
    if base is None:
        return None
    return base * cb.parallel * ctx.settings.derating


def design_current(ctx: Context, c: Circuit, phase: int) -> Optional[float]:
    if c.ib:
        return c.ib
    v3 = c.voltage if c.voltage and c.voltage >= 300 else 380.0
    v1 = c.voltage if c.voltage and c.voltage < 300 else 220.0
    if c.kw:
        pf = ctx.settings.power_factor
        return c.kw * 1000 / (math.sqrt(3) * v3 * pf) if phase == 3 else c.kw * 1000 / (v1 * pf)
    if c.kva:
        return c.kva * 1000 / (math.sqrt(3) * v3) if phase == 3 else c.kva * 1000 / v1
    return None


def _i2_factor(ctx: Context, kind: Optional[str]) -> float:
    return ctx.settings.i2_factor.get(kind or "CB", 1.3)


# ── 규칙 ────────────────────────────────────────────────────────────────
@rule
def not_electrical(ctx: Context) -> Iterable[Finding]:
    if not ctx.elec.is_electrical:
        yield Finding("KEC-000", K, Severity.INFO, "전기 설비 표기 미검출",
                      "전선 규격(예: F-CV 4C 25㎟)이나 차단기(예: MCCB 3P 100AF 75AT) 표기를 찾지 못했습니다. "
                      "KEC 전기 규정 검토 대상이 없습니다(건축·기계 도면이거나 표기가 블록 외부 형상일 수 있음).")


@rule
def overload(ctx: Context) -> Iterable[Finding]:
    out: List[Finding] = []
    for c in ctx.elec.circuits:
        b, cb = c.breaker, c.cable
        row = CircuitRow(breaker=b.label(), cable=cb.label(), in_a=b.at, iz_a=None,
                         result="판정불가", basis=c.basis + (" · LLM 해석" if c.llm else ""))
        ctx.circuits.append(row)
        if not cb.low_voltage or "hv" in c.purposes:
            row.note = "고압 케이블 — 저압 허용전류표 대상 아님"
            continue
        if not b.overload:
            row.note = "과부하 보호 정격(AT) 없음" if b.kind != "RCCB" else "RCCB는 과부하 보호 없음"
            continue
        phase, guessed = phase_of(c)
        loaded = 3 if phase == 3 else 2
        iz = iz_of(ctx, c, loaded)
        if iz is None:
            row.note = "허용전류표 범위 밖 규격(%gSQ)" % cb.size
            continue
        row.iz_a = round(iz, 1)
        In = float(b.at)
        i2 = _i2_factor(ctx, b.kind) * In
        ib = design_current(ctx, c, phase)
        problems = []
        if In > iz + 1e-9:
            problems.append("In %.0fA > Iz %.1fA" % (In, iz))
        if i2 > 1.45 * iz + 1e-9:
            problems.append("I2 %.1fA(=%.2f×In) > 1.45×Iz %.1fA" % (i2, _i2_factor(ctx, b.kind), 1.45 * iz))
        if ib is not None and ib > In + 1e-9:
            problems.append("IB %.1fA > In %.0fA" % (ib, In))
        method = ctx.settings.wire_method if cb.is_wire else ctx.settings.cable_method
        cond = "%s·공사방법 %s·부하도체 %d%s%s" % (
            cb.insulation, method, loaded, "(추정)" if guessed else "",
            "·%d조 병렬%s" % (cb.parallel, "(추정)" if cb.parallel_guessed else "") if cb.parallel > 1 else "")
        row.note = cond
        if not problems:
            row.result = "적합"
            continue
        sev = Severity.WARNING if c.llm else _sev(c.basis)
        if guessed and loaded == 3:
            alt = iz_of(ctx, c, 2)
            if alt is not None and In <= alt and _i2_factor(ctx, b.kind) * In <= 1.45 * alt:
                sev = Severity.WARNING  # 단상이면 적합 — 상수 표기 필요
        row.result = "부적합" if sev == Severity.ERROR else "주의"
        fix = {}
        if In > iz + 1e-9 or i2 > 1.45 * iz + 1e-9:
            need = max(In, i2 / 1.45)
            new = kec.min_size_for_current(cb.insulation, method, loaded, need, cb.parallel, ctx.settings.derating)
            if new and new > cb.size:
                fix = num_fix(c.cable_item, cb.size, new, "size",
                              "전선 %g㎟ → %g㎟ (Iz ≥ %.1fA)" % (cb.size, new, need))
                if fix and c.pe is not None and not c.pe.grounding and c.pe.size < kec.pe_required(new) \
                        and c.pe_item is c.cable_item:
                    fix["ops"].append({"op": "replace_number", "handle": c.cable_item.handle, "old": c.pe.size,
                                       "new": kec.pe_required(new), "unit": "size"})
                    fix["reason"] += ", 보호도체 %g㎟ → %g㎟" % (c.pe.size, kec.pe_required(new))
        out.append(Finding(
            "KEC-212.4.1", K, sev, "과부하 보호 협조 불만족",
            "차단기 [%s] ↔ 전선 [%s]: %s. 허용전류 Iz=%.1fA (%s, 보정계수 %.2f). 전선 굵기를 키우거나 차단기 정격을 낮추세요."
            % (b.label(), cb.label(), "; ".join(problems), iz, cond, ctx.settings.derating),
            kec.OVERLOAD_REF + " · " + kec.AMPACITY_REF, loc(c.anchor, basis=c.basis), c.texts[:4], fix=fix))
    return _cap(ctx, out)


@rule
def min_size(ctx: Context) -> Iterable[Finding]:
    out: List[Finding] = []
    for a in ctx.elec.annotations:
        if "hv" in a.purposes:
            continue
        for cb in a.cables:
            if not cb.low_voltage:
                continue
            if cb.is_control:
                need = kec.MIN_SIZE_CONTROL_MULTICORE if (cb.cores or 0) > 1 else kec.MIN_SIZE_CONTROL
            elif "control" in a.purposes:
                need = kec.MIN_SIZE_CONTROL
            else:
                need = kec.MIN_SIZE_POWER
            if cb.size + 1e-9 < need:
                sev = Severity.ERROR if cb.type else Severity.WARNING
                out.append(Finding(
                    "KEC-231.3.1", K, sev, "전선 최소 굵기 미달",
                    "[%s] %g㎟ < %g㎟. 저압 옥내배선은 2.5㎟ 이상 연동선(제어·표시회로 1.5㎟, 제어용 다심케이블 0.75㎟)을 사용해야 합니다."
                    % (cb.label(), cb.size, need), kec.MIN_SIZE_REF, loc(a.item), [a.item.text],
                    fix=num_fix(a.item, cb.size, need, "size", "최소 굵기 %g㎟ 적용" % need)))
    return _cap(ctx, out)


@rule
def protective_conductor(ctx: Context) -> Iterable[Finding]:
    out: List[Finding] = []
    seen = set()
    for c in ctx.elec.circuits:
        if c.pe is None or c.pe.grounding or not c.cable.low_voltage:
            continue
        seen.add(id(c.pe))
        phase_size = c.cable.size
        need = kec.pe_required(phase_size)
        if c.pe.size + 1e-9 < need:
            out.append(Finding(
                "KEC-142.3.2", K, Severity.WARNING, "보호도체 단면적 부족 (선정표 기준)",
                "상도체 %g㎟에 보호도체 [%s] %g㎟ — 표 142.3-1 기준 %g㎟ 이상 필요. "
                "계산식(142.3.2-1-가)으로 산정했다면 고장전류·차단시간 근거를 도면에 명시하세요."
                % (phase_size, c.pe.raw, c.pe.size, need), kec.PE_REF, loc(c.anchor), c.texts[:3],
                fix=num_fix(c.pe_item, c.pe.size, need, "size", "보호도체 %g㎟ → %g㎟ (표 142.3-1)" % (c.pe.size, need))))
    for pe, item, with_phase in ctx.elec.pes:
        if pe.grounding or with_phase or id(pe) in seen:
            continue
        if pe.size + 1e-9 < kec.PE_SEPARATE_MECH:
            out.append(Finding("KEC-142.3.2", K, Severity.ERROR, "단독 보호도체 굵기 미달",
                               "[%s] %g㎟ — 케이블 일부가 아닌 보호도체는 기계적 보호가 있으면 2.5㎟, 없으면 4㎟ 이상(구리)."
                               % (pe.raw, pe.size), kec.PE_REF, loc(item), [item.text],
                               fix=num_fix(item, pe.size, kec.PE_SEPARATE_NOMECH, "size", "단독 보호도체 4㎟ 적용")))
        elif pe.size + 1e-9 < kec.PE_SEPARATE_NOMECH:
            out.append(Finding("KEC-142.3.2", K, Severity.WARNING, "단독 보호도체 기계적 보호 확인",
                               "[%s] %g㎟ — 기계적 보호(전선관 등)가 없으면 4㎟ 이상이어야 합니다." % (pe.raw, pe.size),
                               kec.PE_REF, loc(item), [item.text],
                               fix=num_fix(item, pe.size, kec.PE_SEPARATE_NOMECH, "size", "단독 보호도체 4㎟ 적용")))
    return _cap(ctx, out)


@rule
def grounding_conductor(ctx: Context) -> Iterable[Finding]:
    out: List[Finding] = []
    for a in ctx.elec.annotations:
        for pe in a.pes:
            if not pe.grounding:
                continue
            lps = "lps" in a.purposes
            need = kec.GROUND_MIN_LPS if lps else kec.GROUND_MIN
            if pe.size + 1e-9 < need:
                out.append(Finding(
                    "KEC-142.3.1", K, Severity.ERROR, "접지도체 굵기 미달",
                    "[%s] %g㎟ — 접지도체는 구리 %g㎟ 이상%s." % (
                        pe.raw, pe.size, need, "(피뢰시스템 접속)" if lps else "(큰 고장전류가 흐르지 않는 경우)"),
                    kec.GROUND_REF, loc(a.item), [a.item.text],
                    fix=num_fix(a.item, pe.size, need, "size", "접지도체 %g㎟ 적용" % need)))
    return _cap(ctx, out)


@rule
def voltage_drop(ctx: Context) -> Iterable[Finding]:
    out: List[Finding] = []
    for c, row in zip(ctx.elec.circuits, ctx.circuits):
        if not c.length_m or not c.cable.low_voltage:
            continue
        phase, _ = phase_of(c)
        ib = design_current(ctx, c, phase)
        if ib is None:
            continue
        wiring = wiring_of(c, phase)
        k = kec.VDROP_K[wiring]
        area = c.cable.size * c.cable.parallel
        e = k * c.length_m * ib / (1000.0 * area)
        v3 = c.voltage if c.voltage and c.voltage >= 300 else 380.0
        v1 = c.voltage if c.voltage and c.voltage < 300 else 220.0
        # 기준 전압: 3P4W·1P3W 계수(17.8)는 대지(중성선)간 전압 기준
        vref = {"1P2W": v1, "3P3W": v3, "3P4W": v3 / math.sqrt(3), "1P3W": v1 / 2}[wiring]
        pct = 100.0 * e / vref
        use = "lighting" if "lighting" in c.purposes else "other"
        limit = kec.vdrop_limit(ctx.settings.supply_type, use, c.length_m)
        row.note = (row.note + " · " if row.note else "") + "전압강하 %.2f%%(한도 %.1f%%)" % (pct, limit)
        if pct > limit + 1e-9:
            e_allow = limit * vref / 100.0
            req = k * c.length_m * ib / (1000.0 * e_allow) / max(1, c.cable.parallel)
            new = kec.next_size(max(req, c.cable.size))
            vfix = num_fix(c.cable_item, c.cable.size, new, "size",
                           "전압강하 %.1f%% 이내: %g㎟ → %g㎟" % (limit, c.cable.size, new)) if new and new > c.cable.size else {}
            out.append(Finding(
                "KEC-232.3.9", K, _sev(c.basis), "전압강하 한도 초과",
                "[%s] L=%gm, I=%.1fA, %s → e=%.2fV (%.2f%%) > %s %s 한도 %.1f%%. 이 구간만으로 한도를 넘었습니다"
                "(수전점부터 누적 기준)." % (c.cable.label(), c.length_m, ib, wiring, e, pct,
                                    "A형(저압 수전)" if ctx.settings.supply_type == "A" else "B형(고압 이상 수전)",
                                    "조명" if use == "lighting" else "기타", limit),
                kec.VDROP_REF, loc(c.anchor), c.texts[:4], fix=vfix))
    return _cap(ctx, out)


@rule
def residual_current(ctx: Context) -> Iterable[Finding]:
    out: List[Finding] = []
    for c in ctx.elec.circuits:
        b = c.breaker
        if "bath" in c.purposes:
            if b.residual and b.ma is not None and b.ma > kec.RCD_BATH_MAX_MA:
                out.append(Finding("KEC-234.5", K, Severity.ERROR, "욕실 등 누전차단기 감도 초과",
                                   "[%s] 정격감도전류 %gmA — 욕실·화장실 등 콘센트 회로는 15mA 이하·0.03초 이하 "
                                   "인체감전보호용 누전차단기가 필요합니다." % (b.label(), b.ma),
                                   kec.RCD_BATH_REF, loc(c.anchor), c.texts[:3],
                                   fix=num_fix(c.anchor, b.ma, kec.RCD_BATH_MAX_MA, "ma", "정격감도전류 15mA 적용")))
            elif not b.residual:
                out.append(Finding("KEC-234.5", K, Severity.WARNING, "욕실 등 인체감전보호 확인",
                                   "[%s] 욕실 계열 회로에 누전차단기 표기가 없습니다. 15mA 인체감전보호용 누전차단기, "
                                   "절연변압기(3kVA 이하) 또는 누전차단기 부착 콘센트를 명시하세요." % b.label(),
                                   kec.RCD_BATH_REF, loc(c.anchor), c.texts[:3]))
            continue
        if c.purposes & {"outlet", "outdoor"}:
            if not b.residual:
                out.append(Finding("KEC-211.2.4", K, Severity.WARNING, "누전차단기 미표기",
                                   "[%s] 콘센트·옥외 회로에 누전차단기(ELB/RCBO) 표기가 없습니다. 사람이 쉽게 접촉할 우려가 있는 "
                                   "50V 초과 기계기구 전로에는 누전차단기를 시설해야 합니다." % b.label(),
                                   kec.RCD_REF, loc(c.anchor), c.texts[:3]))
            elif b.ma is not None and b.ma > kec.RCD_GENERAL_MAX_MA:
                out.append(Finding("KEC-211.2.4", K, Severity.WARNING, "누전차단기 감도 확인",
                                   "[%s] %gmA — 인체 감전 보호 목적이면 30mA 이하 고감도형을 사용하세요." % (b.label(), b.ma),
                                   kec.RCD_REF, loc(c.anchor), c.texts[:3]))
    return _cap(ctx, out)


@rule
def breaker_ratings(ctx: Context) -> Iterable[Finding]:
    out: List[Finding] = []
    for b, item in ctx.elec.breakers:
        if b.at is not None and b.af is not None and b.at > b.af + 1e-9:
            out.append(Finding("KEC-212.3", K, Severity.ERROR, "차단기 정격 모순",
                               "[%s] 정격전류 %gAT가 프레임 %gAF보다 큽니다." % (b.label(), b.at, b.af),
                               "KEC 212.3 · KS C IEC 60947-2", loc(item), [item.text],
                               fix=num_fix(item, b.af, kec.next_frame(b.at), "af",
                                           "프레임 %gAF → %gAF" % (b.af, kec.next_frame(b.at) or 0)) if kec.next_frame(b.at) else {}))
        if b.at is not None and b.at not in kec.STD_AT and b.kind not in ("FUSE",):
            out.append(Finding("KEC-212.3", K, Severity.INFO, "비표준 차단기 정격",
                               "[%s] %gAT는 일반 표준 정격 계열에 없습니다. 제품 정격을 확인하세요." % (b.label(), b.at),
                               "KS C IEC 60947-2", loc(item), [item.text]))
        if b.residual and b.ma is None and b.kind != "RCBO":
            out.append(Finding("KEC-211.2.4", K, Severity.INFO, "정격감도전류 미표기",
                               "[%s] 누전차단기의 정격감도전류(mA)를 표기하세요." % b.label(), kec.RCD_REF, loc(item), [item.text]))
        if b.ma is not None and b.ma not in kec.STD_RCD_MA:
            out.append(Finding("KEC-211.2.4", K, Severity.INFO, "비표준 정격감도전류",
                               "[%s] %gmA는 표준 감도 계열(15·30·100·200·500mA 등)이 아닙니다." % (b.label(), b.ma),
                               "KS C IEC 61008/61009", loc(item), [item.text]))
        big = (b.af or 0) >= 225 or b.kind == "ACB"
        if big and b.ka is None:
            out.append(Finding("KEC-212.5", K, Severity.INFO, "차단용량 미표기",
                               "[%s] 주요 차단기는 설치점 예상 최대 단락전류 이상의 정격차단용량(kA)을 표기하세요." % b.label(),
                               "KEC 212.5 (단락전류에 대한 보호)", loc(item), [item.text]))
    return _cap(ctx, out)


_DEPRECATED = re.compile(r"(특별\s*)?제\s*[1-3]\s*종\s*접지|특\s*3\s*종\s*접지|(?<![A-Z])E\s*[1-3]\s*종")


@rule
def deprecated_terms(ctx: Context) -> Iterable[Finding]:
    out: List[Finding] = []
    for t in ctx.drawing.texts:
        m = _DEPRECATED.search(t.norm)
        if m:
            out.append(Finding("KEC-140", K, Severity.ERROR, "폐지된 종별 접지 표기",
                               "'%s' — KEC 시행(2021.1.1)으로 제1·2·3종·특별 제3종 접지 구분은 폐지되었습니다. "
                               "계통접지(TN/TT/IT)·보호접지·피뢰시스템 접지로 다시 설계·표기하세요." % m.group(0),
                               "KEC 140 (접지시스템) · KEC 203 (계통접지)", loc(t), [t.text],
                               fix=_text_fix(t, m.group(0), "보호접지", "종별 접지 → KEC 보호접지 표기")))
    return _cap(ctx, out)


_KEC_COLOR = {"L1": "갈색", "L2": "흑색", "L3": "회색", "N": "청색", "PE": "녹색-노란색"}


def _text_fix(item, old: str, new: str, reason: str) -> dict:
    if item is None or not item.handle or item.kind.startswith("BLOCK-") or not old:
        return {}
    return {"ops": [{"op": "replace_text", "handle": item.handle, "old": old, "new": new}],
            "reason": reason, "confidence": "rule"}


_COLOR_PAIR = re.compile(r"(?<![A-Z0-9])(L1|L2|L3|N|PE)\s*[:(=\-]?\s*\(?\s*([가-힣][가-힣\-/]*)")
_RST = re.compile(r"(?<![A-Z])[RST]\s*상|(?<![A-Z])R\s*[,·/]\s*S\s*[,·/]\s*T(?![A-Z])")


@rule
def conductor_colors(ctx: Context) -> Iterable[Finding]:
    out: List[Finding] = []
    rst = None
    for t in ctx.drawing.texts:
        for m in _COLOR_PAIR.finditer(t.norm):
            cond, color = m.group(1), m.group(2)
            if not any(ch in color for ch in "갈흑검회청파녹황노빨적백흰"):
                continue
            ok = any(color.startswith(x) or x in color for x in kec.CONDUCTOR_COLORS[cond])
            if not ok:
                out.append(Finding("KEC-121.2", K, Severity.ERROR, "전선 식별 색상 불일치",
                                   "%s를 '%s'(으)로 표기 — KEC 식별 색상은 L1 갈색, L2 흑색, L3 회색, N 청색, PE 녹색-노란색입니다."
                                   % (cond, color), kec.COLOR_REF, loc(t), [t.text],
                                   fix=_text_fix(t, m.group(0), m.group(0).replace(color, _KEC_COLOR[cond]),
                                                 "%s → %s" % (color, _KEC_COLOR[cond]))))
        if rst is None and _RST.search(t.norm):
            rst = t
    if rst is not None:
        out.append(Finding("KEC-121.2", K, Severity.INFO, "구 상(相) 표기",
                           "R·S·T 상 표기가 있습니다. KEC는 L1·L2·L3 표기와 갈·흑·회 색상 식별을 씁니다.",
                           kec.COLOR_REF, loc(rst), [rst.text]))
    return _cap(ctx, out)


_EARTHING = re.compile(r"(?<![A-Z])(TN-C-S|TN-S|TN-C|TT)(?![A-Z])|(?<![A-Z])IT\s*(?:계통|방식|SYSTEM)|계통\s*접지")


@rule
def earthing_system(ctx: Context) -> Iterable[Finding]:
    if not ctx.elec.breakers:
        return
    if any(_EARTHING.search(t.norm) for t in ctx.drawing.texts):
        return
    yield Finding("KEC-203", K, Severity.WARNING, "계통접지 방식 미표기",
                  "차단기가 있는 전기 도면이지만 계통접지 방식(TN-S·TN-C-S·TT·IT)을 찾지 못했습니다. "
                  "보호 방식(누전차단기·과전류차단기에 의한 고장보호) 판단의 전제이므로 단선결선도에 명시하세요.",
                  "KEC 203 (계통접지의 방식)")


_CONDUIT = re.compile(
    r"(?:(?<![A-Z])(HI-PVC|PVC|ST|EMT|CD|PF|FC|GI|G|E)\s*-?\s*(\d{2,3})(?:\s*C)?|(?<![\d.])(\d{2,3})\s*C)(?![\d.A-Z])")


@rule
def conduit_fill(ctx: Context) -> Iterable[Finding]:
    out: List[Finding] = []
    for a in ctx.elec.annotations:
        wires = [c for c in a.cables if c.is_wire]
        if not wires or len(wires) != len(a.cables):
            continue
        m = _CONDUIT.search(a.item.norm)
        if not m:
            continue
        d_in = float(m.group(2) or m.group(3))
        sizes: List[float] = []
        for w in wires:
            sizes += [w.size] * (w.count or 0)
        sizes += [p.size for p in a.pes]
        if not sizes or any(s not in kec.HFIX_OD for s in sizes):
            continue
        area = sum(math.pi / 4 * kec.HFIX_OD[s] ** 2 for s in sizes)
        ratio = 100.0 * area / (math.pi / 4 * d_in ** 2)
        limit = kec.CONDUIT_FILL_SAME if len(set(sizes)) == 1 else kec.CONDUIT_FILL_MIXED
        if ratio > limit:
            out.append(Finding("KEC-232.12", K, Severity.WARNING, "전선관 점유율 초과",
                               "[%s] 전선 %d가닥 피복 포함 %.0f㎟ / 관 %gmm → %.0f%% > %.0f%%. 관 굵기를 키우세요. "
                               "(HFIX 외경·관 내경은 공칭 근사값)" % (a.item.text, len(sizes), area, d_in, ratio, limit),
                               kec.CONDUIT_REF, loc(a.item), [a.item.text]))
    return _cap(ctx, out)


@rule
def high_voltage(ctx: Context) -> Iterable[Finding]:
    hv = [a for a in ctx.elec.annotations if "hv" in a.purposes or any(not c.low_voltage for c in a.cables)]
    if hv:
        yield Finding("KEC-300", K, Severity.INFO, "고압·특고압 설비 포함",
                      "고압/특고압 표기 %d건 — 이격거리·절연내력·보호계전 등 KEC 300편(고압·특고압) 항목은 "
                      "도면 문자만으로 판정하지 않았습니다. 수변전 설계 검토서를 함께 확인하세요." % len(hv),
                      "KEC 300 (고압·특고압 전기설비)", evidence=[a.item.text for a in hv[:5]])


@rule
def unmatched(ctx: Context) -> Iterable[Finding]:
    um = ctx.elec.unmatched_breakers
    if um:
        yield Finding("KEC-212.4.1", K, Severity.INFO, "전선 미연관 차단기",
                      "가까운 전선 규격 표기를 찾지 못한 차단기 %d개 — 과부하 보호 협조를 판정하지 못했습니다." % len(um),
                      kec.OVERLOAD_REF, evidence=["%s (%s)" % (b.label(), t.layer) for b, t in um[:10]])
