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
from .model import Category, FileReport, Finding, PackageReport, Report, Severity
from .profile import FACT_LABEL, Profile, compare_set, compare_sheet
from .rules import Context, run_all
from .rules.kec_rules import _EARTHING
from .rules.set_rules import SetContext, run_set

_SEV_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
_CAT_ORDER = {c: i for i, c in enumerate(
    (Category.FILE, Category.SET, Category.KEC, Category.PROFILE, Category.CAD, Category.DOC))}
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


def _analyze(path: Path, arcname: str, settings: Settings, siblings: Iterable[str] = ()
             ) -> Tuple[FileReport, Optional[Drawing], Optional[ElectricalModel]]:
    fr = FileReport(path=arcname, kind="dxf")
    d = load(path, settings)
    if d.load_error:
        fr.findings.append(Finding("FILE-004", Category.FILE, Severity.ERROR, "DXF 읽기 실패", d.load_error))
        return fr, None, None
    elec = electrical.build(d, settings)
    ctx = Context(drawing=d, elec=elec, settings=settings, arcname=arcname,
                  sibling_files=set(siblings), scale=detect_scale(d))
    fr.findings = _sort(run_all(ctx))
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
    }
    return fr, d, elec


def analyze_dxf(path: Path, arcname: str, settings: Settings, siblings: Iterable[str] = ()) -> FileReport:
    return _analyze(path, arcname, settings, siblings)[0]


def _iter_inputs(paths, settings: Settings, tmp_root: Path, report: Optional[Report]):
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
                analyzed.append(_analyze(f.path, f.arcname, settings, siblings))
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
                  keep_temp: bool = False, profile: Optional[Profile] = None) -> Report:
    settings = settings or Settings()
    report = Report(inputs=[str(p) for p in paths],
                    generated_at=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    settings=settings.to_dict())
    tmp_root = Path(tempfile.mkdtemp(prefix="dxfcheck_"))
    try:
        for name, analyzed, others in _iter_inputs(paths, settings, tmp_root, report):
            pairs = _sheets(analyzed, settings)
            if profile is not None:
                for fr, sh in pairs:
                    fr.findings = _sort(fr.findings + compare_sheet(profile, sh))
            report.files.extend(fr for fr, _, _ in analyzed)
            report.files.extend(others)
            pkg = _package(name, [sh for _, sh in pairs], settings, profile)
            if pkg is not None:
                report.packages.append(pkg)
                # 계통접지 방식은 세트 단위 표기(보통 E-04 단선결선도)로 본다
                if any(_EARTHING.search(t.norm) for _, sh in pairs for t in sh.drawing.texts):
                    for fr, _ in pairs:
                        fr.findings = [f for f in fr.findings if f.rule_id != "KEC-203"]
        if not report.dxf_files:
            report.archive_findings.append(Finding(
                "FILE-001", Category.FILE, Severity.ERROR, "DXF 파일 없음",
                "입력에서 검증할 DXF 파일을 찾지 못했습니다."))
    finally:
        if not keep_temp:
            shutil.rmtree(tmp_root, ignore_errors=True)
    return report


def _package(name: str, sheets: List[Sheet], settings: Settings, profile: Optional[Profile]
             ) -> Optional[PackageReport]:
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
