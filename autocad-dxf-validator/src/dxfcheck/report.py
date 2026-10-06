"""보고서 출력 (Markdown · JSON)."""
from __future__ import annotations

import json
from typing import List

from .model import Category, FileReport, Finding, PackageReport, Report, Severity

_ICON = {Severity.ERROR: "🔴", Severity.WARNING: "🟡", Severity.INFO: "🔵"}
_VERDICT_ICON = {"적합": "✅", "조건부 적합": "⚠️", "부적합": "❌", "검증 불가": "⛔"}


def to_json(report: Report) -> str:
    return json.dumps(report.to_dict(), ensure_ascii=False, indent=2)


def _esc(s: object) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def _finding_md(f: Finding) -> List[str]:
    head = "- %s **[%s] %s** — %s" % (_ICON[f.severity], f.rule_id, f.title, f.message)
    lines = [head]
    meta = []
    if f.reference:
        meta.append("근거: %s" % f.reference)
    if f.location:
        l = f.location
        pos = []
        if l.get("drawing"):
            pos.append("도면 %s" % l["drawing"])
        if l.get("layout") and l.get("layout") != "Model":
            pos.append("배치 %s" % l["layout"])
        if l.get("layer"):
            pos.append("레이어 %s" % l["layer"])
        if "x" in l:
            pos.append("(%s, %s)" % (l["x"], l["y"]))
        if l.get("handle"):
            pos.append("handle %s" % l["handle"])
        if l.get("basis"):
            pos.append("연관: %s" % l["basis"])
        if pos:
            meta.append("위치: " + " · ".join(pos))
    if meta:
        lines.append("  - " + " / ".join(meta))
    if f.evidence:
        ev = ", ".join("`%s`" % _esc(e)[:80] for e in f.evidence[:6])
        lines.append("  - 원문: " + ev)
    return lines


def _file_md(fr: FileReport, idx: int) -> List[str]:
    out = ["", "## %d. %s" % (idx, fr.path), "",
           "**판정: %s %s** · 점수 %d/100 · 부적합 %d · 주의 %d · 참고 %d" % (
               _VERDICT_ICON.get(fr.verdict, ""), fr.verdict, fr.score,
               fr.count(Severity.ERROR), fr.count(Severity.WARNING), fr.count(Severity.INFO))]
    if fr.overview:
        out += ["", "### 도면 개요", "", "| 항목 | 값 |", "|---|---|"]
        out += ["| %s | %s |" % (k, _esc(v)) for k, v in fr.overview.items()]
    if fr.circuits:
        out += ["", "### 회로 대조 (차단기 ↔ 전선, KEC 212.4.1)", "",
                "| # | 차단기 | 전선 | In(A) | Iz(A) | 판정 | 연관 | 조건·비고 |", "|---|---|---|---|---|---|---|---|"]
        for i, c in enumerate(fr.circuits, 1):
            out.append("| %d | %s | %s | %s | %s | %s | %s | %s |" % (
                i, _esc(c.breaker), _esc(c.cable), "%g" % c.in_a if c.in_a is not None else "-",
                "%g" % c.iz_a if c.iz_a is not None else "-", c.result, c.basis, _esc(c.note)))
    out += ["", "### 지적 사항"]
    if not fr.findings:
        out += ["", "지적 사항 없음."]
    for cat in Category:
        items = [f for f in fr.findings if f.category == cat]
        if not items:
            continue
        out += ["", "#### %s (%d)" % (cat.value, len(items)), ""]
        for f in items:
            out += _finding_md(f)
    return out


def _package_md(p: PackageReport) -> List[str]:
    out = ["", "## 도면 세트 정합성 — %s" % p.name, "",
           "부적합 %d · 주의 %d · 참고 %d" % (p.count(Severity.ERROR), p.count(Severity.WARNING), p.count(Severity.INFO))]
    if p.profile:
        out += ["", "- 학습 기준: " + " · ".join("%s %s" % kv for kv in p.profile.items())]
    if p.items21:
        icon = {"적합": "✅", "조건부 적합": "⚠️", "부적합": "❌", "누락": "⛔", "해당없음": "➖"}
        out += ["", "### 도면별 검증 결과 (E-01~E-21)", "", "| 도면 | 도면명 | 판정 | 내용 | 주요 지적 |", "|---|---|---|---|---|"]
        for it in p.items21:
            out.append("| %s | %s | %s %s | %s | %s |" % (
                it["no"], _esc(it["name"]), icon.get(it["status"], ""), it["status"], _esc(it["summary"]),
                _esc(" / ".join(it["issues"])) or "-"))
    if p.sheets:
        out += ["", "### 도면 인식", "", "| 도면번호 | 파일 | 표제란 도면명 | 정본 도면명 | 인식 근거 |", "|---|---|---|---|---|"]
        out += ["| %s | %s | %s | %s | %s |" % tuple(_esc(r[k]) for k in ("도면번호", "파일", "표제란 도면명", "정본 도면명", "인식 근거"))
                for r in p.sheets]
    if p.facts:
        cols = sorted({k for row in p.facts.values() for k in row if k != "설계값"})
        has_meta = any("설계값" in row for row in p.facts.values())
        if has_meta:
            cols = ["설계값"] + cols
        out += ["", "### 도면 간 설계 수치 대조", "", "| 항목 | " + " | ".join(cols) + " |",
                "|---|" + "---|" * len(cols)]
        for fact, row in p.facts.items():
            vals = [row.get(c, "") for c in cols]
            distinct = {v for c, v in row.items() if v}
            mark = " ⚠" if len(distinct) > 1 else ""
            out.append("| %s%s | %s |" % (fact, mark, " | ".join(_esc(v) for v in vals)))
    out += ["", "### 세트 지적 사항", ""]
    if not p.findings:
        out.append("지적 사항 없음.")
    for f in p.findings:
        out += _finding_md(f)
    return out


def to_markdown(report: Report) -> str:
    v = report.verdict
    out = ["# DXF 도면 검증 보고서 (KEC 기준)", "",
           "- 입력: %s" % ", ".join("`%s`" % i for i in report.inputs),
           "- 분석 일시: %s" % report.generated_at,
           "- 대상: DXF %d개 / 전체 %d개" % (len(report.dxf_files), len(report.files)),
           "- **종합 판정: %s %s** — 부적합 %d · 주의 %d · 참고 %d" % (
               _VERDICT_ICON.get(v, ""), v, report.total(Severity.ERROR),
               report.total(Severity.WARNING), report.total(Severity.INFO))]
    if report.llm:
        out.append("- 미인식 표기 LLM 해석: " + " · ".join("%s %s" % kv for kv in report.llm.items()))
    if report.files:
        out += ["", "| 파일 | 판정 | 점수 | 부적합 | 주의 | 참고 |", "|---|---|---|---|---|---|"]
        for fr in report.files:
            out.append("| %s | %s %s | %s | %d | %d | %d |" % (
                _esc(fr.path), _VERDICT_ICON.get(fr.verdict, ""), fr.verdict,
                fr.score if fr.kind == "dxf" else "-", fr.count(Severity.ERROR),
                fr.count(Severity.WARNING), fr.count(Severity.INFO)))
    if report.archive_findings:
        out += ["", "## 압축·입력 점검", ""]
        for f in report.archive_findings:
            out += _finding_md(f)
    for p in report.packages:
        out += _package_md(p)
    for i, fr in enumerate(report.files, 1):
        out += _file_md(fr, i)
    s = report.settings
    out += ["", "## 검토 기준과 한계", "",
            "- 판정 기준: KEC(한국전기설비규정) — 212.4.1 과부하 보호, 231.3.1 최소 굵기, 142.3.1/142.3.2 접지·보호도체, "
            "232.3.9 전압강하, 211.2.4/234.5 누전차단기, 121.2 전선 식별, 140/203 접지계통. "
            "허용전류는 KS C IEC 60364-5-52 부속서 B(구리·30℃) 값을 씁니다.",
            "- 적용 조건: 케이블 공사방법 %s, 절연전선 %s, 보정계수 %.2f, 전압강하 %s형, 역률 %.2f "
            "(`--config`로 변경)." % (s.get("cable_method"), s.get("wire_method"), s.get("derating", 1.0),
                                    s.get("supply_type"), s.get("power_factor", 0.9)),
            "- 도면 세트는 'AutoCAD 자동화 설계' 6장의 E-01~E-21 검증 항목을 따릅니다. 기준값은 XRECORD 설계 메타데이터, "
            "없으면 도면 간 다수값입니다.",
            "- LLM은 규칙이 읽지 못한 문자만 '해석'합니다(원문에 없는 숫자는 버림). 판정은 해석된 값에 같은 공식을 적용하며, "
            "그 결과는 '(LLM 해석)'으로 표시하고 '주의' 이하로 낮춥니다.",
            "- 학습 기준 비교는 승인된 기준 도면의 통계 프로파일(레이어·글꼴·블록·표제란·표준 문구·수치 항목)과의 차이입니다.",
            "- 도면 '문자' 표기를 읽어 판정합니다. 선(형상)만 그려진 결선, 블록 밖 기호, 표기 오기는 판정할 수 없습니다.",
            "- 차단기↔전선 연관은 같은 문자 → 같은 행 → 근접 순으로 추정하며, 근접 추정 결과는 '주의'로 낮춰 표시합니다.",
            "- 이 보고서는 설계 검토 보조 자료입니다. 최종 적합 판단은 전기 설계·감리 기술자가 합니다."]
    return "\n".join(out) + "\n"
