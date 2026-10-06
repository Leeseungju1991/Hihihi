"""CAD 품질 규칙 — 도면 파일이 실무에서 그대로 쓰일 수 있는가."""
from __future__ import annotations

import re
from pathlib import PureWindowsPath
from typing import Iterable

from ..drawing import INSUNITS_NAME, unit_to_mm
from ..model import Category, Finding, Severity
from . import Context, rule

C = Category.CAD
_HANGUL = re.compile("[가-힣]")
_KOREAN_SHX = ("WHGTXT", "WHGDTXT", "WHTGTXT", "WHTMTXT", "HGTXT", "HANGUL", "KS", "GHS", "SHGT", "WHG")
_TTF = (".TTF", ".TTC", ".OTF")


def _f(rid, sev, title, msg, ref="", **kw) -> Finding:
    return Finding(rid, C, sev, title, msg, ref, **kw)


@rule
def audit(ctx: Context) -> Iterable[Finding]:
    d = ctx.drawing
    if d.audit_errors:
        yield _f("CAD-001", Severity.ERROR, "DXF 구조 오류",
                 "감사(audit)에서 구조 오류 %d건이 발견되었습니다. AutoCAD에서 AUDIT/RECOVER 후 다시 저장하세요."
                 % len(d.audit_errors), evidence=d.audit_errors[:10])
    elif d.audit_fixes:
        yield _f("CAD-001", Severity.WARNING, "DXF 자동 복구 항목",
                 "읽는 중 자동 수정된 항목이 %d건 있습니다. 원본 저장 프로그램의 호환성을 확인하세요." % d.audit_fixes)


@rule
def version(ctx: Context) -> Iterable[Finding]:
    d = ctx.drawing
    if d.dxfversion and d.dxfversion <= "AC1015":
        yield _f("CAD-002", Severity.INFO, "오래된 DXF 버전",
                 "%s(%s) 형식입니다. 협업 기준 버전(예: R2013 이상)으로 저장을 권장합니다."
                 % (d.release, d.dxfversion))


@rule
def units(ctx: Context) -> Iterable[Finding]:
    d = ctx.drawing
    if d.insunits == 0:
        yield _f("CAD-003", Severity.WARNING, "도면 단위 미지정",
                 "$INSUNITS가 '단위 없음'입니다. 블록 삽입·외부참조 시 축척이 틀어질 수 있습니다. "
                 "전기 도면은 mm 단위를 권장합니다(UNITS 명령).")
    elif d.insunits != 4:
        yield _f("CAD-003", Severity.INFO, "도면 단위가 mm가 아님",
                 "도면 단위가 %s입니다. 국내 전기 설계도면은 mm 단위가 일반적입니다."
                 % INSUNITS_NAME.get(d.insunits, str(d.insunits)))


@rule
def empty(ctx: Context) -> Iterable[Finding]:
    d = ctx.drawing
    if d.total_entities == 0:
        yield _f("CAD-004", Severity.ERROR, "빈 도면", "모형·배치 공간에 객체가 하나도 없습니다.")
    elif d.model_entities == 0:
        yield _f("CAD-004", Severity.WARNING, "모형 공간 비어 있음",
                 "모형 공간에 객체가 없고 배치 공간에만 그려져 있습니다.")


@rule
def layer_zero(ctx: Context) -> Iterable[Finding]:
    d = ctx.drawing
    total = d.total_entities
    n0 = d.layer_count.get("0", 0)
    if total >= 20 and n0 / total >= ctx.settings.layer0_ratio_warn:
        yield _f("CAD-005", Severity.WARNING, "레이어 0 과다 사용",
                 "전체 객체의 %.0f%%(%d/%d)가 레이어 0에 있습니다. 설비 종류별(전등·전열·동력·접지 등)로 "
                 "레이어를 나누세요." % (100.0 * n0 / total, n0, total))
    if len(d.layers) <= 1 and total > 0:
        yield _f("CAD-005", Severity.WARNING, "레이어 구분 없음", "레이어가 0 하나뿐입니다.")


@rule
def unused_layers(ctx: Context) -> Iterable[Finding]:
    d = ctx.drawing
    unused = [li.name for k, li in d.layers.items()
              if k not in d.layer_count and k not in ("0", "DEFPOINTS")]
    if len(unused) >= 5:
        yield _f("CAD-006", Severity.INFO, "미사용 레이어",
                 "객체가 없는 레이어 %d개 — PURGE로 정리를 권장합니다." % len(unused), evidence=unused[:20])


@rule
def hidden_layers(ctx: Context) -> Iterable[Finding]:
    d = ctx.drawing
    if d.hidden_layer_objects:
        ev = ["%s: %d개" % (k, v) for k, v in d.hidden_layer_objects.most_common(10)]
        yield _f("CAD-007", Severity.WARNING, "꺼짐/동결 레이어에 객체",
                 "출력·검토 시 보이지 않는 객체가 %d개 있습니다. 누락된 설비 표기가 없는지 확인하세요."
                 % sum(d.hidden_layer_objects.values()), evidence=ev)
    noplot = [li.name for k, li in d.layers.items()
              if not li.plot and d.layer_count.get(k, 0) and k != "DEFPOINTS"]
    if noplot:
        yield _f("CAD-007", Severity.INFO, "출력 안 함 레이어에 객체",
                 "플롯 해제된 레이어에 객체가 있습니다.", evidence=noplot[:20])


@rule
def defpoints(ctx: Context) -> Iterable[Finding]:
    n = ctx.drawing.defpoints_objects
    if n:
        yield _f("CAD-008", Severity.WARNING, "Defpoints 레이어 객체",
                 "Defpoints 레이어의 객체 %d개는 출력되지 않습니다." % n)


@rule
def geometry(ctx: Context) -> Iterable[Finding]:
    d = ctx.drawing
    if d.zero_length:
        yield _f("CAD-009", Severity.WARNING, "길이 0 선분",
                 "길이가 0인 LINE %d개 — 결선 오인·스냅 오류 원인이 됩니다." % len(d.zero_length),
                 evidence=["handle %s (레이어 %s)" % x for x in d.zero_length[:10]])
    if d.duplicate_lines:
        yield _f("CAD-009", Severity.WARNING, "중복 선분",
                 "완전히 겹친 LINE %d개 — OVERKILL로 정리하세요. 물량 산출이 부풀려집니다." % len(d.duplicate_lines),
                 evidence=["handle %s (레이어 %s)" % x for x in d.duplicate_lines[:10]])


def _basename(p: str) -> str:
    return PureWindowsPath(p).name.lower() if p else ""


@rule
def xrefs(ctx: Context) -> Iterable[Finding]:
    for name, path in ctx.drawing.xrefs:
        base = _basename(path)
        alt = base.rsplit(".", 1)[0] + ".dxf" if base else ""
        if base and (base in ctx.sibling_files or alt in ctx.sibling_files):
            yield _f("CAD-010", Severity.INFO, "외부참조 포함됨",
                     "외부참조 '%s'(%s)가 압축에 함께 있습니다. 바인드(BIND) 후 제출을 권장합니다." % (name, path))
        else:
            yield _f("CAD-010", Severity.ERROR, "외부참조 누락",
                     "외부참조 '%s'(%s) 파일이 압축에 없습니다. 해당 내용은 검증되지 않았습니다." % (name, path))


@rule
def images(ctx: Context) -> Iterable[Finding]:
    for p in ctx.drawing.images:
        if _basename(p) not in ctx.sibling_files:
            yield _f("CAD-011", Severity.WARNING, "이미지 참조 누락",
                     "참조 이미지 '%s'가 압축에 없습니다. 출력 시 빈 틀로 나옵니다." % p)


@rule
def proxies(ctx: Context) -> Iterable[Finding]:
    n = ctx.drawing.proxies
    if n:
        yield _f("CAD-012", Severity.WARNING, "프록시/미지원 객체",
                 "응용 프로그램 전용 객체 %d개 — 다른 환경에서 표시·편집되지 않을 수 있습니다." % n)


@rule
def dim_overrides(ctx: Context) -> Iterable[Finding]:
    ov = ctx.drawing.dim_overrides
    if ov:
        yield _f("CAD-013", Severity.WARNING, "치수 문자 임의 수정",
                 "측정값 대신 직접 입력한 치수 문자 %d개 — 실제 거리와 다를 수 있습니다." % len(ov),
                 evidence=["handle %s: '%s' (레이어 %s)" % (h, t, l) for h, l, t in ov[:10]])


@rule
def korean_fonts(ctx: Context) -> Iterable[Finding]:
    d = ctx.drawing
    risky = {}
    for t in d.texts:
        if not _HANGUL.search(t.text):
            continue
        font, big = d.styles.get(t.style.upper(), ("", ""))
        fu, bu = font.upper(), big.upper()
        if fu.endswith(_TTF) or not fu:
            continue
        if bu or any(k in fu for k in _KOREAN_SHX):
            continue
        risky.setdefault(t.style, 0)
        risky[t.style] += 1
    for style, n in risky.items():
        font = d.styles.get(style.upper(), ("", ""))[0]
        yield _f("CAD-014", Severity.WARNING, "한글 글꼴 깨짐 위험",
                 "문자 스타일 '%s'(글꼴 %s)에 한글 빅폰트가 없어 한글 문자 %d개가 '?'로 보일 수 있습니다. "
                 "whgtxt.shx 등 빅폰트나 TTF 글꼴을 지정하세요." % (style, font, n))


@rule
def text_height(ctx: Context) -> Iterable[Finding]:
    d = ctx.drawing
    u = unit_to_mm(d.insunits)
    if u is None:
        return
    min_h = ctx.settings.min_text_height_mm
    small, checked = [], 0
    for t in d.texts:
        if t.h <= 0:
            continue
        if t.layout == "Model":
            if not ctx.scale:
                continue
            paper = t.h * u / ctx.scale
        else:
            paper = t.h * u
        checked += 1
        if paper < min_h - 1e-6:
            small.append((t, paper))
    if small:
        ev = ["'%s' %.2fmm (%s)" % (t.text[:30], p, t.layer) for t, p in small[:10]]
        basis = "축척 1/%d 기준" % ctx.scale if ctx.scale else "배치 공간 기준"
        yield _f("CAD-015", Severity.WARNING, "출력 문자 높이 부족",
                 "출력 시 %.1fmm 미만이 되는 문자 %d/%d개(%s). 판독성을 위해 %.1fmm 이상을 권장합니다."
                 % (min_h, len(small), checked, basis, min_h), "KS A ISO 3098-1", evidence=ev)
    elif not ctx.scale and any(t.layout == "Model" for t in d.texts):
        yield _f("CAD-015", Severity.INFO, "문자 높이 검토 생략",
                 "축척 표기를 찾지 못해 모형 공간 문자의 출력 높이는 검토하지 않았습니다.")


@rule
def color_bylayer(ctx: Context) -> Iterable[Finding]:
    d = ctx.drawing
    total = d.total_entities
    if total >= 50 and d.non_bylayer_color / total > 0.5:
        yield _f("CAD-016", Severity.INFO, "객체 색상 직접 지정",
                 "객체 %.0f%%가 ByLayer가 아닌 색상을 씁니다. 레이어 기준 관리가 어렵습니다."
                 % (100.0 * d.non_bylayer_color / total))


@rule
def extents(ctx: Context) -> Iterable[Finding]:
    e = ctx.drawing.extents
    if not e:
        return
    (x0, y0), (x1, y1) = e
    span = max(x1 - x0, y1 - y0)
    if span > 1e8 or max(abs(x0), abs(y0), abs(x1), abs(y1)) > 1e9:
        yield _f("CAD-017", Severity.WARNING, "도면 범위 비정상",
                 "도면 범위가 %.3g 단위로 매우 큽니다. 원점에서 멀리 떨어진 객체가 있는지 확인하세요(ZOOM E)." % span)
