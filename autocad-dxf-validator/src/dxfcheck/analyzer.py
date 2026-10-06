"""입력(ZIP·DXF·폴더) → 검증 보고서."""
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
from .drawing import INSUNITS_NAME, detect_scale, is_dwg, load
from .model import Category, FileReport, Finding, Report, Severity
from .rules import Context, run_all

_SEV_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
_CAT_ORDER = {Category.FILE: 0, Category.KEC: 1, Category.CAD: 2, Category.DOC: 3}
CAD_EXT = {".dxf", ".dwg", ".dwf", ".dws", ".dwt"}


def _collect(path: Path, settings: Settings, tmp_root: Path) -> Tuple[List[ExtractedFile], List[Finding]]:
    if path.is_dir():
        files = [ExtractedFile(p, str(p.relative_to(path))) for p in sorted(path.rglob("*")) if p.is_file()]
        return files, []
    if path.suffix.lower() == ".zip":
        dest = Path(tempfile.mkdtemp(prefix="unzip_", dir=str(tmp_root)))
        res = extract_zip(path, dest, settings, prefix=path.name)
        return res.files, res.findings
    return [ExtractedFile(path, path.name)], []


def analyze_paths(paths: Sequence[Union[str, Path]], settings: Optional[Settings] = None,
                  keep_temp: bool = False) -> Report:
    settings = settings or Settings()
    report = Report(inputs=[str(p) for p in paths],
                    generated_at=_dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
                    settings=settings.to_dict())
    tmp_root = Path(tempfile.mkdtemp(prefix="dxfcheck_"))
    try:
        for raw in paths:
            p = Path(raw)
            if not p.exists():
                report.archive_findings.append(Finding("FILE-000", Category.FILE, Severity.ERROR, "입력 없음",
                                                       "%s 경로가 없습니다." % p))
                continue
            files, findings = _collect(p, settings, tmp_root)
            report.archive_findings.extend(findings)
            siblings = {f.path.name.lower() for f in files} | {Path(f.arcname).name.lower() for f in files}
            others: Counter = Counter()
            for f in files:
                ext = f.path.suffix.lower()
                if ext == ".dxf" and not is_dwg(f.path):
                    report.files.append(analyze_dxf(f.path, f.arcname, settings, siblings))
                elif ext == ".dwg" or (ext == ".dxf" and is_dwg(f.path)):
                    fr = FileReport(path=f.arcname, kind="dwg")
                    fr.findings.append(Finding(
                        "FILE-002", Category.FILE, Severity.WARNING, "DWG 파일 — 직접 검증 불가",
                        "DWG는 비공개 이진 형식이라 검증하지 않았습니다. AutoCAD 'DXFOUT'(다른 이름으로 저장 → DXF) "
                        "또는 ODA File Converter로 DXF로 변환해 다시 첨부하세요."))
                    report.files.append(fr)
                else:
                    others[ext or "(확장자 없음)"] += 1
            if others:
                report.archive_findings.append(Finding(
                    "FILE-003", Category.FILE, Severity.INFO, "도면 외 파일",
                    "%s: DXF가 아닌 파일 %d개는 검증 대상에서 제외했습니다." % (p.name, sum(others.values())),
                    evidence=["%s × %d" % kv for kv in others.most_common()]))
        if not report.dxf_files:
            report.archive_findings.append(Finding(
                "FILE-001", Category.FILE, Severity.ERROR, "DXF 파일 없음",
                "입력에서 검증할 DXF 파일을 찾지 못했습니다."))
    finally:
        if not keep_temp:
            shutil.rmtree(tmp_root, ignore_errors=True)
    return report


def analyze_dxf(path: Path, arcname: str, settings: Settings, siblings: Iterable[str] = ()) -> FileReport:
    fr = FileReport(path=arcname, kind="dxf")
    d = load(path, settings)
    if d.load_error:
        fr.findings.append(Finding("FILE-004", Category.FILE, Severity.ERROR, "DXF 읽기 실패", d.load_error))
        return fr
    elec = electrical.build(d, settings)
    ctx = Context(drawing=d, elec=elec, settings=settings, arcname=arcname,
                  sibling_files=set(siblings), scale=detect_scale(d))
    fr.findings = sorted(run_all(ctx), key=lambda f: (_SEV_ORDER[f.severity], _CAT_ORDER[f.category], f.rule_id))
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
    }
    return fr
