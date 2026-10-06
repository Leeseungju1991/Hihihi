"""입력(ZIP·DXF·폴더) → 검증 보고서 / 학습 프로파일."""
from __future__ import annotations

import datetime as _dt
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple, Union

from . import electrical
from .archive import ExtractedFile, extract_zip
from .config import Settings
from .drawing import INSUNITS_NAME, Drawing, detect_scale, is_dwg, load
from .drawingset import CATALOG, Sheet, build_sheet, metadata_facts
from .electrical import ElectricalModel
from .llm import LLMSession, LLMStats, find_candidates, interpret
from .model import Category, FileReport, Finding, PackageReport, Report, Severity
from .profile import FACT_LABEL, Profile, compare_set, compare_sheet
from .rules import Context, run_all
from .rules.kec_rules import _EARTHING
from .rules.set_rules import SetContext, run_set

_SEV_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
_CAT_ORDER = {c: i for i, c in enumerate(
    (Category.FILE, Category.SET, Category.KEC, Category.PROFILE, Category.CAD, Category.DOC, Category.LLM))}
_TABLE_FACTS = ("capacity_kw", "module_count", "module_w", "inverter_count", "inverter_kw", "series", "parallel",
                "dc_fuse_a", "mppt", "dc_sq", "ac_sq", "receiving", "install_type", "tray_type")


def _sort(findings: List[Finding]) -> List[Finding]:
    return sorted(findings, key=lambda f: (_SEV_ORDER[f.severity], _CAT_ORDER[f.category], f.rule_id))


def _collect(path: Path, settings: Settings, tmp_root: Path) -> Tuple[List[ExtractedFile], List[Finding]]:
    if path.is_dir():
        files = [ExtractedFile(p, str(p.relative_to(path))) for p in sorted(path.rglob("*")) if p.is_file()]
        return files, []
    if path.suffix.lower() == ".zip":
        dest = Path(tempfile.mkdtemp(prefix="unzip_", dir=str(tmp_root)))
        res = extract_zip(path, dest, settings, prefix=path.name)
        return res.files, res.findings
    return [ExtractedFile(path, path.name)], []


_LLM_NOTE = " ※ 규칙이 읽지 못한 표기를 LLM이 해석한 값으로 같은 공식을 적용했습니다 — 원문을 확인하세요."


def _downgrade_llm(findings: List[Finding], st: LLMStats) -> None:
    """LLM 해석 값이 들어간 지적은 '주의' 이하로 낮추고 표시한다."""
    if not st.resolved_handles:
        return
    for f in findings:
        if f.category not in (Category.KEC, Category.CAD, Category.DOC):
            continue
        hit = f.location.get("handle") in st.resolved_handles or any(e in st.resolved_texts for e in f.evidence)
        if hit and "(LLM 해석)" not in f.title:
            if f.severity == Severity.ERROR:
                f.severity = Severity.WARNING
            f.title += " (LLM 해석)"
            f.message += _LLM_NOTE


def _llm_findings(st: LLMStats) -> List[Finding]:
    out: List[Finding] = []
    if not st.candidates:
        return out
    if not st.enabled:
        out.append(Finding("LLM-000", Category.LLM, Severity.INFO, "미인식 표기",
                           "전기·설계 표기로 보이지만 규칙이 읽지 못한 문자 %d건 — 판정에서 빠졌습니다. "
                           "`--llm vertex`로 켜면 이 문자만 LLM이 해석하고, 판정은 같은 공식으로 합니다." % st.candidates,
                           evidence=st.unresolved_samples[:10]))
        return out
    out.append(Finding("LLM-001", Category.LLM, Severity.INFO, "미인식 표기 LLM 해석",
                       st.summary() + ". 채택한 값으로 내린 판정은 '(LLM 해석)'으로 표시하고 '주의' 이하로 낮췄습니다.",
                       evidence=st.rejected_samples[:5] + ["오류: " + e for e in st.errors[:3]]))
    if st.unresolved:
        out.append(Finding("LLM-002", Category.LLM, Severity.INFO, "해석되지 않은 표기",
                           "LLM으로도 해석하지 못했거나 예산 한도로 보내지 않은 문자 %d건 — 수동 확인이 필요합니다." % st.unresolved,
                           evidence=st.unresolved_samples[:10]))
    return out


def _analyze(path: Path, arcname: str, settings: Settings, siblings: Iterable[str] = (),
             llm: Optional[LLMSession] = None
             ) -> Tuple[FileReport, Optional[Drawing], Optional[ElectricalModel]]:
    fr = FileReport(path=arcname, kind="dxf")
    d = load(path, settings)
    if d.load_error:
        fr.findings.append(Finding("FILE-004", Category.FILE, Severity.ERROR, "DXF 읽기 실패", d.load_error))
        return fr, None, None
    anns = electrical.parse_all(d)
    st = interpret(d, anns, find_candidates(d, anns), llm)
    elec = electrical.build(d, settings, anns)
    ctx = Context(drawing=d, elec=elec, settings=settings, arcname=arcname,
                  sibling_files=set(siblings), scale=detect_scale(d))
    findings = run_all(ctx)
    _downgrade_llm(findings, st)
    for f in findings:
        f.file = f.file or arcname
    fr.findings = _sort(findings + _llm_findings(st))
    fr.circuits = ctx.circuits
    ext = ""
    if d.extents:
        (x0, y0), (x1, y1) = d.extents
        ext = "%.0f × %.0f" % (x1 - x0, y1 - y0)
    fr.overview = {
        "DXF 버전": "%s (%s)" % (d.release, d.dxfversion),
        "도면 단위": INSUNITS_NAME.get(d.insunits, str(d.insunits)),
        "축척": "1/%d" % ctx.scale if ctx.scale else "미확인",
        "도면 범위": ext or "-",
        "레이어": len(d.layers),
        "객체": d.total_entities,
        "객체 유형": ", ".join("%s %d" % kv for kv in d.entity_count.most_common(8)),
        "문자": len(d.texts),
        "블록 삽입": sum(d.blocks_used.values()),
        "배치(Layout)": ", ".join("%s %d" % kv for kv in d.layout_count.most_common()),
        "전선 표기": len(elec.cables),
        "차단기 표기": len(elec.breakers),
        "회로 대조": len(elec.circuits),
        "설계 메타데이터": "%d개 키" % len(d.metadata) if d.metadata else "없음",
        "미인식 표기 / LLM": st.summary() if st.candidates else "없음",
    }
    return fr, d, elec


def analyze_dxf(path: Path, arcname: str, settings: Settings, siblings: Iterable[str] = (),
                llm: Optional[LLMSession] = None) -> FileReport:
    return _analyze(path, arcname, settings, siblings, llm)[0]


def _iter_inputs(paths, settings: Settings, tmp_root: Path, report: Optional[Report],
                 llm: Optional[LLMSession] = None):
    """입력마다 (이름, [(FileReport, Drawing, Elec)], 기타 FileReport) 를 낸다."""
    for raw in paths:
        p = Path(raw)
        if not p.exists():
            if report is not None:
                report.archive_findings.append(Finding("FILE-000", Category.FILE, Severity.ERROR, "입력 없음",
                                                       "%s 경로가 없습니다." % p))
            continue
        files, findings = _collect(p, settings, tmp_root)
        if report is not None:
            report.archive_findings.extend(findings)
        siblings = {f.path.name.lower() for f in files} | {Path(f.arcname).name.lower() for f in files}
        analyzed, others_fr = [], []
        others: Counter = Counter()
        for f in files:
            ext = f.path.suffix.lower()
            if ext == ".dxf" and not is_dwg(f.path):
                analyzed.append(_analyze(f.path, f.arcname, settings, siblings, llm))
            elif ext == ".dwg" or (ext == ".dxf" and is_dwg(f.path)):
                fr = FileReport(path=f.arcname, kind="dwg")
                fr.findings.append(Finding(
                    "FILE-002", Category.FILE, Severity.WARNING, "DWG 파일 — 직접 검증 불가",
                    "DWG는 비공개 이진 형식이라 검증하지 않았습니다. AutoCAD 'DXFOUT'(다른 이름으로 저장 → DXF) "
                    "또는 ODA File Converter로 DXF로 변환해 다시 첨부하세요."))
                others_fr.append(fr)
            else:
                others[ext or "(확장자 없음)"] += 1
        if others and report is not None:
            report.archive_findings.append(Finding(
                "FILE-003", Category.FILE, Severity.INFO, "도면 외 파일",
                "%s: DXF가 아닌 파일 %d개는 검증 대상에서 제외했습니다." % (p.name, sum(others.values())),
                evidence=["%s × %d" % kv for kv in others.most_common()]))
        yield p.name, analyzed, others_fr


def _sheets(analyzed, settings: Settings) -> List[Tuple[FileReport, Sheet]]:
    return [(fr, build_sheet(fr.path, d, e, settings)) for fr, d, e in analyzed if d is not None]


def analyze_paths(paths: Sequence[Union[str, Path]], settings: Optional[Settings] = None,
                  keep_temp: bool = False, profile: Optional[Profile] = None,
                  llm: Optional[LLMSession] = None) -> Report:
    settings = settings or Settings()
    report = Report(inputs=[str(p) for p in paths],
                    generated_at=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    settings=settings.to_dict())
    tmp_root = Path(tempfile.mkdtemp(prefix="dxfcheck_"))
    try:
        for name, analyzed, others in _iter_inputs(paths, settings, tmp_root, report, llm):
            pairs = _sheets(analyzed, settings)
            if profile is not None:
                for fr, sh in pairs:
                    fr.findings = _sort(fr.findings + compare_sheet(profile, sh))
            report.files.extend(fr for fr, _, _ in analyzed)
            report.files.extend(others)
            # 계통접지 방식은 세트 단위 표기(보통 E-04 단선결선도)로 본다
            if any(sh.no for _, sh in pairs) and \
                    any(_EARTHING.search(t.norm) for _, sh in pairs for t in sh.drawing.texts):
                for fr, _ in pairs:
                    fr.findings = [f for f in fr.findings if f.rule_id != "KEC-203"]
            pkg = _package(name, [sh for _, sh in pairs], settings, profile, {fr.path: fr for fr, _ in pairs})
            if pkg is not None:
                report.packages.append(pkg)
        if not report.dxf_files:
            report.archive_findings.append(Finding(
                "FILE-001", Category.FILE, Severity.ERROR, "DXF 파일 없음",
                "입력에서 검증할 DXF 파일을 찾지 못했습니다."))
        cands = sum(1 for fr in report.files for f in fr.findings if f.rule_id in ("LLM-000", "LLM-001"))
        if llm is not None and llm.complete is not None:
            report.llm = {"상태": "켜짐", "모델": llm.model_tag or "-", "요약": llm.total.summary()}
            llm.save()
        elif cands:
            report.llm = {"상태": "꺼짐", "요약": "미인식 표기가 있는 도면 %d개 (--llm vertex 로 해석 가능)" % cands}
    finally:
        if not keep_temp:
            shutil.rmtree(tmp_root, ignore_errors=True)
    return report


_PRESENCE_LABEL = {"whm": "WHM 계량기", "pen": "PEN", "pe": "보호접지(PE)", "bonding": "등전위본딩", "clamp": "접지 클램프",
                   "polarity": "(+)/(−) 극성", "spacing": "지지 간격", "thickness": "부재 두께", "bolt": "볼트",
                   "ground_caption": "접지선 규격", "mppt_word": "MPPT", "string_word": "스트링", "inverter_word": "인버터"}
_UNIT = {"capacity_kw": "kW", "inverter_kw": "kW", "module_count": "장", "module_w": "W", "inverter_count": "대",
         "series": "직렬", "parallel": "병렬", "dc_fuse_a": "A", "mppt": "", "dc_sq": "㎟", "ac_sq": "㎟",
         "mccb_at": "AT", "string_vmax": "V", "inverter_vmax": "V"}


def _fmtv(v) -> str:
    return ("%g" % v) if isinstance(v, (int, float)) and not isinstance(v, bool) else str(v)


def items21(sheets: List[Sheet], set_findings: List[Finding], files: dict, agreed: dict) -> List[dict]:
    """E-01~E-21 도면별 결과: 상태 · 내용 단어(keywords) · 요약 · 주요 지적."""
    out = []
    rcv = str(agreed.get("receiving", ""))
    for no, (name, _) in CATALOG.items():
        sh = [s for s in sheets if s.no == no]
        if not sh:
            status = "해당없음" if (no == "E-15" and rcv in ("고압", "HV")) else "누락"
            rel = [f for f in set_findings if no in f.message and f.severity != Severity.INFO]
            out.append({"no": no, "name": name, "status": status, "files": [], "keywords": [],
                        "summary": "도면 없음" if status == "누락" else "고압 수전 — 제외 대상",
                        "errors": sum(f.severity == Severity.ERROR for f in rel),
                        "warnings": sum(f.severity == Severity.WARNING for f in rel),
                        "issues": [f.title for f in rel[:3]], "finding_ids": [f.id for f in rel]})
            continue
        kw: List[str] = []
        for s in sh:
            for fact in ("capacity_kw", "module_count", "module_w", "inverter_count", "inverter_kw", "mppt",
                         "dc_fuse_a", "dc_sq", "ac_sq", "mccb_at", "receiving", "install_type", "tray_type",
                         "string_vmax"):
                v = s.value(fact)
                if v is None:
                    continue
                label = FACT_LABEL.get(fact, fact).split("(")[0]
                word = "%s %s%s" % (label, _fmtv(v), _UNIT.get(fact, ""))
                if word not in kw:
                    kw.append(word)
            if s.value("series") and s.value("parallel"):
                w = "%d직렬×%d병렬" % (s.value("series"), s.value("parallel"))
                if w not in kw:
                    kw.append(w)
            for k in s.present:
                lab = _PRESENCE_LABEL.get(k)
                if lab and lab not in kw:
                    kw.append(lab)
        rel = [f for f in set_findings if f.location.get("drawing", "").startswith(no) or
               any(op.get("file") in [s.arcname for s in sh] for op in f.fix.get("ops", []))]
        for s in sh:
            fr = files.get(s.arcname)
            if fr is not None:
                rel += [f for f in fr.findings if f.category != Category.LLM]
        rel = [f for f in rel if f.severity != Severity.INFO]
        e = sum(f.severity == Severity.ERROR for f in rel)
        w = sum(f.severity == Severity.WARNING for f in rel)
        out.append({"no": no, "name": name, "status": "부적합" if e else "조건부 적합" if w else "적합",
                    "files": [s.arcname for s in sh], "keywords": kw[:12],
                    "summary": " · ".join(kw[:6]) if kw else (sh[0].title or name),
                    "errors": e, "warnings": w, "issues": [f.title for f in _sort(rel)[:3]],
                    "finding_ids": [f.id for f in rel]})
    return out


def _package(name: str, sheets: List[Sheet], settings: Settings, profile: Optional[Profile],
             files: Optional[dict] = None) -> Optional[PackageReport]:
    numbered = [s for s in sheets if s.no]
    if not numbered:
        return None   # 도면번호(E-xx)가 없으면 단일 도면 검증만
    meta = metadata_facts(sheets, settings)
    raw = {}
    for s in sheets:
        for k, v in s.drawing.metadata.items():
            raw.setdefault(k, v)
    ctx = SetContext(sheets=sheets, meta=meta, meta_raw=raw, settings=settings)
    findings = run_set(ctx)
    if not meta:
        findings.append(Finding("SET-000", Category.SET, Severity.INFO, "설계 메타데이터 없음",
                                "XRECORD 설계 메타데이터를 찾지 못해 도면 간 다수값을 기준으로 대조했습니다. "
                                "계산서 값과의 직접 대조는 하지 않았습니다."))
    if profile is not None:
        findings.extend(compare_set(profile, sheets))
    pkg = PackageReport(name=name, findings=_sort(findings), metadata={k: v for k, v in meta.items()})
    for s in sorted(sheets, key=lambda x: (x.no or "Z", x.sub or 0, x.arcname)):
        pkg.sheets.append({"도면번호": (s.no or "-") + ("-%d" % s.sub if s.sub else ""), "파일": s.arcname,
                           "표제란 도면명": s.title or "-",
                           "정본 도면명": CATALOG[s.no][0] if s.no else "-", "인식 근거": s.source or "-"})
    for fact in _TABLE_FACTS:
        row = {}
        for s in numbered:
            v = s.value(fact)
            if v is not None:
                key = s.no + ("-%d" % s.sub if s.sub else "")
                row[key] = ("%g" % v) if isinstance(v, float) else str(v)
        if fact in meta:
            mv = meta[fact]
            row["설계값"] = ("%g" % mv) if isinstance(mv, (int, float)) and not isinstance(mv, bool) else str(mv)
        if row:
            pkg.facts[FACT_LABEL.get(fact, fact)] = row
    if profile is not None:
        pkg.profile = profile.summary()
    pkg.items21 = items21(sheets, pkg.findings, files or {}, ctx.agreed)
    return pkg


# ── 학습 ────────────────────────────────────────────────────────────────
def learn_paths(paths: Sequence[Union[str, Path]], settings: Optional[Settings] = None,
                profile: Optional[Profile] = None) -> Tuple[Profile, List[str]]:
    """기준 도면(승인본)에서 프로파일을 학습한다. 반환: (프로파일, 학습 로그)."""
    settings = settings or Settings()
    profile = profile or Profile()
    log: List[str] = []
    tmp_root = Path(tempfile.mkdtemp(prefix="dxfcheck_learn_"))
    try:
        for name, analyzed, _ in _iter_inputs(paths, settings, tmp_root, None):
            pairs = _sheets(analyzed, settings)
            n = profile.learn_set(name, [sh for _, sh in pairs])
            errs = sum(fr.count(Severity.ERROR) for fr, _ in pairs)
            log.append("%s: 도면 %d개 학습 (도면번호 인식 %d개)%s" % (
                name, n, sum(1 for _, s in pairs if s.no),
                " — 주의: 기준 도면에 부적합 %d건. 승인된 도면인지 확인하세요." % errs if errs else ""))
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
    return profile, log
