"""도면 세트 규칙 — 'AutoCAD 자동화 설계' 6장 도면별 검증 항목.

기준값 우선순위: XRECORD 설계 메타데이터 → (없으면) 도면 간 다수값.
도면 간 수치가 다르면 '부적합', 도면에 있어야 할 표기가 없으면 '주의'.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from ..config import Settings
from ..drawing import TextItem, detect_scale, normalize, unit_to_mm
from ..drawingset import CATALOG, CONDITIONAL, NO_RE, Sheet, corpus_key
from ..model import Category, Finding, Severity
from ..profile import FACT_LABEL

S = Category.SET


@dataclass
class SetContext:
    sheets: List[Sheet]
    meta: Dict[str, object]          # 표준 사실명으로 바꾼 메타데이터
    meta_raw: Dict[str, object]      # XRECORD 원본(펼친 키)
    settings: Settings
    agreed: Dict[str, object] = field(default_factory=dict)   # 사실별 기준값

    def by_no(self, no: str) -> List[Sheet]:
        return [s for s in self.sheets if s.no == no]

    def first(self, no: str) -> Optional[Sheet]:
        lst = self.by_no(no)
        return lst[0] if lst else None

    @property
    def numbers(self) -> set:
        return {s.no for s in self.sheets if s.no}


SetRule = Callable[[SetContext], Iterable[Finding]]
SET_RULES: List[SetRule] = []


def set_rule(fn: SetRule) -> SetRule:
    SET_RULES.append(fn)
    return fn


def _f(rid: str, sev: Severity, title: str, msg: str, sheet: Optional[Sheet] = None,
       item: Optional[TextItem] = None, ref: str = "AutoCAD 자동화 설계 6장", evidence=None) -> Finding:
    loc: Dict[str, object] = {}
    if sheet is not None:
        loc["drawing"] = "%s (%s)" % (sheet.no or "?", sheet.arcname)
    if item is not None:
        loc.update(layer=item.layer, layout=item.layout, handle=item.handle, x=round(item.x, 2), y=round(item.y, 2))
    return Finding(rid, S, sev, title, msg, ref, loc, list(evidence or []))


def _close(a, b, tol_pct: float) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return str(a).strip().upper() == str(b).strip().upper()
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= max(abs(b), 1e-9) * tol_pct / 100.0 + 1e-9


def _fmt(v) -> str:
    if isinstance(v, float):
        return ("%.3f" % v).rstrip("0").rstrip(".")
    return str(v)


def _meta_num(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v.replace(",", ""))
        except ValueError:
            return v
    return v


def consistency(ctx: SetContext, rid: str, fact: str, nos: Sequence[str]) -> List[Finding]:
    """사실 `fact`가 도면 `nos`에서 서로(또는 메타데이터와) 같은지 본다."""
    label = FACT_LABEL.get(fact, fact)
    rows = [(s, s.value(fact)) for no in nos for s in ctx.by_no(no) if s.value(fact) is not None]
    tol = ctx.settings.set_tolerance_pct
    out: List[Finding] = []
    meta = ctx.meta.get(fact)
    if meta is not None:
        meta = _meta_num(meta)
        ctx.agreed[fact] = meta
        for s, v in rows:
            if not _close(v, meta, tol):
                out.append(_f(rid, Severity.WARNING if s.is_llm(fact, v) else Severity.ERROR,
                              "%s 불일치 (설계 메타데이터)%s" % (label, " (LLM 해석)" if s.is_llm(fact, v) else ""),
                              "%s의 %s %s ≠ 설계값 %s" % (s.no, label, _fmt(v), _fmt(meta)), s, s.where(fact),
                              evidence=[s.where(fact).text] if s.where(fact) else []))
        return out
    if not rows:
        return out
    cnt = Counter(_fmt(v) for _, v in rows)
    major = cnt.most_common(1)[0][0]
    ctx.agreed.setdefault(fact, next(v for _, v in rows if _fmt(v) == major))
    if len(cnt) > 1:
        ev = ["%s: %s" % (s.no, _fmt(v)) for s, v in rows]
        bad = [(s, v) for s, v in rows if _fmt(v) != major]
        llm = any(s.is_llm(fact, v) for s, v in rows)
        out.append(_f(rid, Severity.WARNING if llm else Severity.ERROR,
                      "도면 간 %s 불일치%s" % (label, " (LLM 해석 포함)" if llm else ""),
                      "%s 값이 도면마다 다릅니다(다수값 %s). 불일치 도면: %s%s" % (
                          label, major, ", ".join(sorted({s.no for s, _ in bad})),
                          " ※ 일부 값은 LLM 해석 — 원문 확인" if llm else ""),
                      bad[0][0], bad[0][0].where(fact), evidence=ev))
    return out


# ── 세트 구성 ───────────────────────────────────────────────────────────
def e01_listing(ctx: SetContext) -> Dict[str, str]:
    """E-01 목록표에 적힌 {도면번호: 도면명}."""
    s = ctx.first("E-01")
    if s is None:
        return {}
    texts = [t for t in s.drawing.texts if t.kind != "ATTRIB"]
    out: Dict[str, str] = {}
    for t in texts:
        m = NO_RE.match(t.norm)
        if not m or m.start() != 0:
            continue
        no = "E-%02d" % int(m.group(1))
        if no not in CATALOG:
            continue
        name = t.text[m.end():].strip(" :-·\t") if len(t.norm) > m.end() else ""
        if not name:   # 같은 행 오른쪽 문자
            row = [u for u in texts if u is not t and abs(u.y - t.y) <= 0.75 * max(t.h, u.h, 1e-6) and u.x > t.x]
            row.sort(key=lambda u: u.x)
            name = row[0].text.strip() if row and not NO_RE.match(row[0].norm) else ""
        out.setdefault(no, name)
    return out


_key = corpus_key


@set_rule
def completeness(ctx: SetContext) -> Iterable[Finding]:
    listed = e01_listing(ctx)
    present = ctx.numbers
    dup = Counter((s.no, s.sub) for s in ctx.sheets if s.no)
    for (no, sub), n in dup.items():
        if n > 1:
            yield _f("SET-001", Severity.ERROR, "도면번호 중복",
                     "%s%s 도면이 %d개 있습니다." % (no, "-%d" % sub if sub else "", n),
                     evidence=[s.arcname for s in ctx.sheets if (s.no, s.sub) == (no, sub)])
    if listed:
        for no in sorted(set(listed) - present):
            yield _f("SET-E01-1", Severity.ERROR, "목록표에 있으나 파일 없음",
                     "E-01 목록표의 %s %s 도면 파일이 없습니다." % (no, listed[no]), ctx.first("E-01"))
        for no in sorted(present - set(listed) - {"E-01"}):
            yield _f("SET-E01-1", Severity.ERROR, "파일은 있으나 목록표에 없음",
                     "%s 도면이 생성되었지만 E-01 목록표에 없습니다." % no, ctx.first(no))
        for no, name in sorted(listed.items()):
            s = ctx.first(no)
            if s and name and s.title and _key(name) not in _key(s.title) and _key(s.title) not in _key(name):
                yield _f("SET-E01-1", Severity.WARNING, "목록표 도면명 불일치",
                         "E-01 목록표 '%s' ↔ %s 표제란 '%s'" % (name, no, s.title), s)
    else:
        if "E-01" not in present:
            yield _f("SET-E01-1", Severity.WARNING, "도면 목록표(E-01) 없음",
                     "목록표가 없어 파일 목록 1:1 대조를 하지 못했습니다.")
        missing = sorted(set(CATALOG) - present - CONDITIONAL)
        if missing:
            yield _f("SET-001", Severity.WARNING, "정본 도면 누락",
                     "정본 도면 목록(E-01~E-21) 중 없는 도면: %s" % ", ".join(missing), evidence=missing)


@set_rule
def content_matches_number(ctx: SetContext) -> Iterable[Finding]:
    for s in ctx.sheets:
        if not s.no:
            continue
        name, words = CATALOG[s.no]
        if not any(_key(w) in s.corpus for w in words):
            yield _f("SET-002", Severity.WARNING, "도면번호와 내용 불일치",
                     "%s(%s) 도면에서 '%s' 관련 표기를 찾지 못했습니다. 도면번호 부여를 확인하세요."
                     % (s.no, name, "/".join(words)), s)


@set_rule
def company_name(ctx: SetContext) -> Iterable[Finding]:
    name = ctx.settings.company_name
    if not name:
        return
    key = _key(name)
    missing = [s for s in ctx.sheets if key not in s.corpus]
    if missing:
        yield _f("SET-E01-2", Severity.WARNING, "표제란 회사명 누락",
                 "'%s' 표기가 없는 도면 %d개" % (name, len(missing)),
                 evidence=["%s (%s)" % (s.no or "?", s.arcname) for s in missing[:15]])


# ── 용량·수량 ───────────────────────────────────────────────────────────
@set_rule
def capacity(ctx: SetContext) -> Iterable[Finding]:
    yield from consistency(ctx, "SET-E01-3", "capacity_kw", ("E-01", "E-02", "E-03", "E-04", "E-09"))
    yield from consistency(ctx, "SET-E02-1", "module_count", ("E-02", "E-04", "E-09", "E-10"))
    yield from consistency(ctx, "SET-E02-1", "inverter_count", ("E-02", "E-04", "E-09", "E-10"))
    yield from consistency(ctx, "SET-E02-1", "module_w", ("E-02", "E-04", "E-12"))
    yield from consistency(ctx, "SET-E04-2", "inverter_kw", ("E-02", "E-04", "E-13"))
    cap, n, w = ctx.agreed.get("capacity_kw"), ctx.agreed.get("module_count"), ctx.agreed.get("module_w")
    if cap is not None and n and w:
        designed = float(n) * float(w) / 1000.0
        if not _close(cap, designed, max(ctx.settings.set_tolerance_pct, 1.0)):
            target = ctx.meta_raw.get("p_pv_kw")
            hint = " 목표 용량(p_pv_kw=%s)을 그대로 적은 것으로 보입니다." % target if (
                target is not None and _close(cap, _meta_num(target), 0.1)) else ""
            yield _f("SET-E01-3", Severity.ERROR, "설계 용량 ≠ 모듈 수 × 모듈 출력",
                     "표기 용량 %skW, 실제 설계 용량 %d장 × %dW = %skW.%s" % (_fmt(cap), n, w, _fmt(designed), hint))


@set_rule
def strings(ctx: SetContext) -> Iterable[Finding]:
    yield from consistency(ctx, "SET-E04-1", "series", ("E-04", "E-08", "E-09", "E-10"))
    yield from consistency(ctx, "SET-E04-1", "parallel", ("E-04", "E-08", "E-09", "E-10"))
    sr, pr, n, inv = (ctx.agreed.get(k) for k in ("series", "parallel", "module_count", "inverter_count"))
    if sr and pr and n:
        ok = int(sr) * int(pr) == int(n) or (inv and int(sr) * int(pr) * int(inv) == int(n))
        if not ok:
            yield _f("SET-E02-2", Severity.WARNING, "직병렬 구성과 모듈 수량 불일치",
                     "%d직렬 × %d병렬%s ≠ 모듈 %d장" % (int(sr), int(pr), " × 인버터 %d대" % int(inv) if inv else "", int(n)))
    vs = [(s, s.value("string_vmax")) for s in ctx.sheets if s.value("string_vmax")]
    vi = [(s, s.value("inverter_vmax")) for s in ctx.sheets if s.value("inverter_vmax")]
    if vs:
        s, v = max(vs, key=lambda x: x[1])
        if v > 1500:
            yield _f("SET-E02-3", Severity.ERROR, "최대 스트링 전압이 저압 범위 초과",
                     "최대 스트링 전압 %sV > DC 1,500V. KEC 111.1 저압(직류 1.5kV 이하) 범위를 넘습니다." % _fmt(v),
                     s, s.where("string_vmax"), "KEC 111.1")
        if vi:
            si, lim = min(vi, key=lambda x: x[1])
            if v > lim:
                yield _f("SET-E02-3", Severity.ERROR, "최대 스트링 전압 > 인버터 최대 입력전압",
                         "스트링 %sV > 인버터 %sV (최저 기온 보정 전압으로 직렬 수를 다시 산정)" % (_fmt(v), _fmt(lim)), s,
                         s.where("string_vmax"))


@set_rule
def fuses_and_mppt(ctx: SetContext) -> Iterable[Finding]:
    yield from consistency(ctx, "SET-E04-3", "dc_fuse_a", ("E-04", "E-09", "E-10"))
    yield from consistency(ctx, "SET-E10-1", "mppt", ("E-10", "E-13", "E-21"))
    s21 = ctx.first("E-21")
    mppt = ctx.agreed.get("mppt")
    if s21 is not None and mppt:
        ch = {v for v, _ in s21.facts.get("mppt_channel", [])}
        if ch and len(ch) != int(mppt):
            yield _f("SET-E21-1", Severity.ERROR, "MPPT 채널 매핑 불일치",
                     "E-21 MPPT 채널 %d개 ≠ MPPT 수 %d" % (len(ch), int(mppt)), s21)


# ── 케이블 ──────────────────────────────────────────────────────────────
def _sizes(s: Optional[Sheet], fact: str) -> set:
    return {v for v, _ in s.facts.get(fact, [])} if s else set()


def _sq(v: float) -> str:
    return "%gSQ" % v


@set_rule
def cables(ctx: SetContext) -> Iterable[Finding]:
    e04, e05 = ctx.first("E-04"), ctx.first("E-05")
    suspects = {normalize(x) for x in ctx.settings.hardcode_suspects}
    for fact in ("ac_sq", "dc_sq"):
        meta = ctx.meta.get(fact)
        s05 = _sizes(e05, fact)
        if meta is not None and s05:
            meta = float(_meta_num(meta))
            if meta not in s05:
                hard = sorted(v for v in s05 if _sq(v) in suspects)
                yield _f("SET-E05-1", Severity.ERROR, "간선 규격 ≠ KEC 계산서",
                         "E-05 %s 케이블 %s — 계산서 산정값 %s 없음.%s" % (
                             "AC" if fact == "ac_sq" else "DC", ", ".join(_sq(v) for v in sorted(s05)), _sq(meta),
                             " 하드코딩 의심 값: %s" % ", ".join(_sq(v) for v in hard) if hard else ""), e05)
        elif e04 is not None and s05:
            s04 = _sizes(e04, fact)
            extra = sorted(s05 - s04)
            if s04 and extra:
                hard = [v for v in extra if _sq(v) in suspects]
                yield _f("SET-E05-1", Severity.ERROR if hard else Severity.WARNING,
                         "간선도·단선결선도 케이블 규격 불일치" + (" (하드코딩 의심)" if hard else ""),
                         "E-05에만 있는 규격 %s (E-04: %s)" % (
                             ", ".join(_sq(v) for v in extra), ", ".join(_sq(v) for v in sorted(s04))), e05)
    meta_dc = ctx.meta.get("dc_sq")
    for s in ctx.by_no("E-11"):
        for v, t in s.facts.get("dc_sq", []):
            if meta_dc is not None and not _close(v, float(_meta_num(meta_dc)), 0.1):
                yield _f("SET-E11-2", Severity.ERROR, "DC 케이블 단면적 ≠ 계산서",
                         "%s %s ≠ 설계값 %s" % (s.no, _sq(v), _sq(float(_meta_num(meta_dc)))), s, t)
                break
            if v + 1e-9 < ctx.settings.dc_cable_min_sq:
                yield _f("SET-E11-2", Severity.WARNING, "DC 케이블 단면적 기준 미달",
                         "%s %s < 기준 %s" % (s.no, _sq(v), _sq(ctx.settings.dc_cable_min_sq)), s, t,
                         "설계 기준 dc_cable_min_sq [근거 확인 필요]")
                break


@set_rule
def inverter_pages(ctx: SetContext) -> Iterable[Finding]:
    pages = ctx.by_no("E-11")
    inv = ctx.agreed.get("inverter_count")
    if not pages or not inv:
        return
    n = len(pages)
    if n == 1:
        n = max(1, len(pages[0].drawing.paper_layouts))
    if n != int(inv):
        yield _f("SET-E11-1", Severity.ERROR, "DC 간선도 페이지 수 ≠ 인버터 수",
                 "E-11 %d페이지(파일 또는 배치) ≠ 인버터 %d대" % (n, int(inv)), pages[0])


# ── 수전·설치 형태·옵션 ─────────────────────────────────────────────────
@set_rule
def receiving(ctx: SetContext) -> Iterable[Finding]:
    yield from consistency(ctx, "SET-E03-1", "receiving", ("E-02", "E-03", "E-04"))
    rcv = ctx.agreed.get("receiving")
    if isinstance(rcv, str):
        rcv = "저압" if rcv.upper() in ("LV", "LOW", "저압") else "고압" if rcv.upper() in ("HV", "HIGH", "고압", "특고압") else rcv
    has15 = bool(ctx.by_no("E-15"))
    if rcv == "저압" and not has15:
        yield _f("SET-E15-1", Severity.WARNING, "LV-M 외형도(E-15) 누락", "저압 수전인데 E-15 도면이 없습니다.")
    elif rcv == "고압" and has15:
        yield _f("SET-E15-1", Severity.WARNING, "고압 수전에 E-15 포함",
                 "고압 수전이면 E-15(LV-M 계량기형)는 제외하거나 사양을 바꿔야 합니다.", ctx.first("E-15"))


@set_rule
def install_and_tray(ctx: SetContext) -> Iterable[Finding]:
    yield from consistency(ctx, "SET-E19-1", "install_type", ("E-02", "E-16", "E-19"))
    yield from consistency(ctx, "SET-E17-1", "tray_type", ("E-05", "E-17", "E-18"))
    if ctx.agreed.get("install_type") == "지상형" and "E-16" not in ctx.numbers:
        yield _f("SET-E16-1", Severity.WARNING, "울타리/대문 상세도(E-16) 누락", "지상형 설치인데 E-16 도면이 없습니다.")
    s16 = ctx.first("E-16")
    if s16 and not re.search(r"기초|콘크리트|CONC", s16.corpus):
        yield _f("SET-E16-1", Severity.WARNING, "울타리 기초 규격 미표기", "E-16에 기초 콘크리트 표기가 없습니다.", s16)


def _meta_bool(v) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    return None


@set_rule
def models_and_options(ctx: SetContext) -> Iterable[Finding]:
    raw = {k.rsplit(".", 1)[-1].lower(): v for k, v in ctx.meta_raw.items()}
    for key, nos, label in (("inverter_model", ("E-02", "E-13", "E-14"), "인버터 모델"),
                            ("module_model", ("E-02", "E-12"), "모듈 모델")):
        val = raw.get(key)
        if not val:
            continue
        for no in nos:
            s = ctx.first(no)
            if s and _key(str(val)) not in s.corpus:
                yield _f("SET-E13-1", Severity.WARNING, "%s 표기 불일치" % label,
                         "%s에 선택한 %s '%s' 표기가 없습니다." % (no, label, val), s)
    s12 = ctx.first("E-12")
    dims = {k: v for k, v in raw.items() if k.startswith("module_") and
            any(x in k for x in ("width", "height", "length", "depth", "thick", "weight"))}
    if s12 and dims:
        nums = set()
        for t in s12.drawing.texts:
            nums.update(float(x.replace(",", "")) for x in re.findall(r"\d[\d,]*(?:\.\d+)?", t.norm))
        for k, v in dims.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if not any(abs(fv - n) <= 0.01 * max(fv, 1) for n in nums):
                yield _f("SET-E12-1", Severity.ERROR, "모듈 치수 ≠ 카탈로그",
                         "E-12에 %s=%s 값이 없습니다." % (k, _fmt(fv)), s12)
    skip = _meta_bool(raw.get("skip_inverter_outline", raw.get("skip_outline")))
    s14 = ctx.first("E-14")
    if s14 is not None and skip:
        outline = [b for b in s14.drawing.blocks_used if re.search(r"INV|OUTLINE|외형", b.upper())]
        if outline:
            yield _f("SET-E14-1", Severity.WARNING, "외형 심볼 스킵 옵션 미반영",
                     "외형 심볼 스킵을 선택했지만 E-14에 외형 블록이 있습니다.", s14, evidence=outline[:5])


# ── 도면별 필수 표기 ────────────────────────────────────────────────────
EXPECT: Dict[str, List[Tuple[str, str]]] = {
    "E-03": [("whm", "한전 계량기(WHM)"), ("*receiving", "수전 방식(저압/고압)")],
    "E-04": [("*series", "모듈 직병렬 수"), ("*mccb_at", "차단기 정격(AT/AF)"), ("*dc_fuse_a", "DC 퓨즈 용량")],
    "E-05": [("ground_caption", "접지선 캡션(예: TFR-GV 16㎟)")],
    "E-06": [("pen", "주접지선(한전 PEN)"), ("pe", "외함 보호접지(PE)"), ("bonding", "보호등전위본딩")],
    "E-07": [("clamp", "접지 클램프 사양"), ("ground_caption", "구조물 접지선 규격")],
    "E-08": [("polarity", "(+)/(−) 극성"), ("*series", "스트링 구성(직렬×병렬)")],
    "E-09": [("inverter_word", "인버터"), ("string_word", "스트링")],
    "E-10": [("mppt_word", "MPPT 채널"), ("*dc_fuse_a", "DC 퓨즈 용량")],
    "E-11": [("*dc_sq", "DC 케이블 단면적")],
    "E-15": [("whm", "계량기 장착")],
    "E-17": [("*tray_type", "트레이 유형(래더/타공/솔리드)")],
    "E-18": [("spacing", "지지대 설치 간격")],
    "E-19": [("*install_type", "설치 형태")],
    "E-20": [("thickness", "부재 두께"), ("bolt", "볼트 사양")],
    "E-21": [("*mppt_channel", "MPPT 채널별 스트링 매핑")],
}


@set_rule
def required_notation(ctx: SetContext) -> Iterable[Finding]:
    for s in ctx.sheets:
        miss = []
        for key, label in EXPECT.get(s.no or "", []):
            ok = bool(s.facts.get(key[1:])) if key.startswith("*") else bool(s.present.get(key))
            if not ok:
                miss.append(label)
        if miss:
            yield _f("SET-%s-P" % (s.no or "E-00").replace("-", ""), Severity.WARNING, "필수 표기 누락",
                     "%s(%s)에서 찾지 못한 항목: %s" % (s.no, CATALOG[s.no][0], ", ".join(miss)), s, evidence=miss)


# ── 도면 공통 (단위 표기·영역·축척 왜곡·레이어) ─────────────────────────
@set_rule
def notation_and_layout(ctx: SetContext) -> Iterable[Finding]:
    std = {l.upper() for l in ctx.settings.standard_layers}
    pw, ph = sorted(ctx.settings.paper_size_mm, reverse=True)[:2]
    for s in ctx.sheets:
        d = s.drawing
        if s.mm2_raw:
            yield _f("SET-P91", Severity.WARNING, "단면적 단위 'mm²' 사용",
                     "%s: 'mm²/mm2' 표기 %d개 — CAD 글꼴 호환을 위해 '㎟'를 쓰세요." % (s.no or s.arcname, len(s.mm2_raw)),
                     s, s.mm2_raw[0], "AutoCAD 자동화 설계 9장", [t.text for t in s.mm2_raw[:5]])
        if d.nonuniform_inserts:
            sev = Severity.WARNING if s.no == "E-03" else Severity.INFO
            yield _f("SET-E03-2", sev, "블록 비균일 축척(스케일 왜곡)",
                     "%s: X/Y 축척이 다른 블록 %d개" % (s.no or s.arcname, len(d.nonuniform_inserts)), s,
                     evidence=["%s (%.3g × %.3g)" % (n, sx, sy) for n, sx, sy, _ in d.nonuniform_inserts[:8]])
        if std:
            bad = sorted(l for l, v in d.layer_count.items() if v and l not in std)
            if bad:
                yield _f("SET-E04-4", Severity.WARNING, "비표준 레이어 사용",
                         "%s: 표준 레이어 목록에 없는 레이어 %d개" % (s.no or s.arcname, len(bad)), s, evidence=bad[:15])
        if s.no in ("E-04", "E-05") and d.extents:
            u = unit_to_mm(d.insunits) or 1.0
            scale = detect_scale(d) or 1
            (x0, y0), (x1, y1) = d.extents
            w, h = sorted(((x1 - x0) * u / scale, (y1 - y0) * u / scale), reverse=True)
            if (w > pw * 1.02 or h > ph * 1.02) and (detect_scale(d) or w < pw * 10):
                yield _f("SET-E04-5", Severity.WARNING, "A3 도면 영역 초과",
                         "%s: 출력 크기 약 %.0f × %.0fmm > A3 %.0f × %.0fmm (축척 1/%d 기준)" % (s.no, w, h, pw, ph, scale), s)
        for name, lw, lh in d.paper_layouts:
            if s.no in ("E-04", "E-05") and lw and lh and max(lw, lh) > pw * 1.02:
                yield _f("SET-E04-5", Severity.WARNING, "배치 용지가 A3보다 큼",
                         "%s 배치 '%s' 용지 %.0f × %.0fmm" % (s.no, name, lw, lh), s)


def run_set(ctx: SetContext) -> List[Finding]:
    out: List[Finding] = []
    for fn in SET_RULES:
        out.extend(fn(ctx))
    return out

