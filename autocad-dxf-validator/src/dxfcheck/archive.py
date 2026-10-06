"""ZIP 안전 해제.

첨부 압축은 신뢰하지 않는 입력이다. 경로 이탈(zip slip)·심볼릭 링크·압축 폭탄·암호화 항목을
걸러내고, 한글 Windows 압축(cp949 파일명)을 복원한다. 중첩 ZIP은 한도 내에서 재귀 해제한다.
"""
from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import List, Tuple

from .config import Settings
from .model import Category, Finding, Severity


@dataclass
class ExtractedFile:
    path: Path      # 디스크 경로
    arcname: str    # 보고서용 압축 내부 경로 (중첩 시 outer.zip/inner.zip/a.dxf)


@dataclass
class ExtractResult:
    files: List[ExtractedFile] = field(default_factory=list)
    findings: List[Finding] = field(default_factory=list)
    total_bytes: int = 0


def _decode_name(info: zipfile.ZipInfo) -> str:
    name = info.filename
    if info.flag_bits & 0x800:  # UTF-8 플래그
        return name
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name
    for enc in ("utf-8", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return name


def _safe_rel(name: str) -> Tuple[bool, PurePosixPath]:
    name = name.replace("\\", "/")
    p = PurePosixPath(name)
    if name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return False, p
    if any(part == ".." for part in p.parts):
        return False, p
    parts = [x for x in p.parts if x not in ("", ".")]
    return True, PurePosixPath(*parts) if parts else PurePosixPath("_")


def _f(sev: Severity, rid: str, title: str, msg: str) -> Finding:
    return Finding(rid, Category.FILE, sev, title, msg)


def extract_zip(zip_path: Path, dest: Path, settings: Settings, prefix: str = "", depth: int = 0,
                result: ExtractResult = None) -> ExtractResult:
    result = result or ExtractResult()
    label = prefix or zip_path.name
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        result.findings.append(_f(Severity.ERROR, "ZIP-001", "손상된 압축 파일",
                                  "%s: ZIP 형식이 아니거나 손상되었습니다." % label))
        return result

    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = _decode_name(info)
            arc = (prefix + "/" if prefix else "") + name
            if len(result.files) >= settings.max_archive_files:
                result.findings.append(_f(Severity.WARNING, "ZIP-002", "파일 수 한도 초과",
                                          "%d개를 넘는 항목은 건너뛰었습니다." % settings.max_archive_files))
                break
            ok, rel = _safe_rel(name)
            if not ok:
                result.findings.append(_f(Severity.ERROR, "ZIP-003", "위험한 경로 항목 제외",
                                          "%s: 압축 밖으로 벗어나는 경로라 해제하지 않았습니다." % arc))
                continue
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                result.findings.append(_f(Severity.WARNING, "ZIP-004", "심볼릭 링크 제외",
                                          "%s: 링크 항목은 해제하지 않았습니다." % arc))
                continue
            if info.flag_bits & 0x1:
                result.findings.append(_f(Severity.ERROR, "ZIP-005", "암호화된 항목",
                                          "%s: 암호가 걸려 있어 열 수 없습니다." % arc))
                continue
            if info.compress_size and info.file_size / max(1, info.compress_size) > settings.max_compression_ratio:
                result.findings.append(_f(Severity.ERROR, "ZIP-006", "압축 폭탄 의심",
                                          "%s: 압축률이 비정상적으로 높아 해제하지 않았습니다." % arc))
                continue
            if result.total_bytes + info.file_size > settings.max_archive_bytes:
                result.findings.append(_f(Severity.ERROR, "ZIP-007", "해제 용량 한도 초과",
                                          "%s 이후 항목은 용량 한도로 해제하지 않았습니다." % arc))
                break

            target = dest.joinpath(*rel.parts)
            # 같은 이름 충돌 방지
            n = 1
            while target.exists():
                target = target.with_name("%s~%d%s" % (target.stem, n, target.suffix))
                n += 1
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            try:
                with zf.open(info) as src, open(target, "wb") as out:
                    while True:
                        chunk = src.read(1 << 20)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > info.file_size + 1024:  # 헤더 크기 위조 방지
                            raise ValueError("size mismatch")
                        out.write(chunk)
            except Exception as exc:  # noqa: BLE001
                result.findings.append(_f(Severity.ERROR, "ZIP-008", "항목 해제 실패",
                                          "%s: %s" % (arc, exc)))
                target.unlink(missing_ok=True)
                continue
            result.total_bytes += written

            if target.suffix.lower() == ".zip":
                if depth + 1 > settings.max_archive_depth:
                    result.findings.append(_f(Severity.WARNING, "ZIP-009", "중첩 압축 깊이 초과",
                                              "%s: 더 이상 풀지 않았습니다." % arc))
                    continue
                sub = target.with_name(target.name + "_unzipped")
                sub.mkdir(parents=True, exist_ok=True)
                extract_zip(target, sub, settings, prefix=arc, depth=depth + 1, result=result)
                continue
            result.files.append(ExtractedFile(target, arc))
    return result
