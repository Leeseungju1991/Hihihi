"""명령행: dxfcheck <ZIP|DXF|폴더>... [-f md|json|both] [-o 출력경로] [--config 설정.json]"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .analyzer import analyze_paths
from .config import Settings
from .model import Severity
from .report import to_json, to_markdown


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="dxfcheck", description="AutoCAD DXF 도면 검증 (KEC 기준)")
    ap.add_argument("inputs", nargs="+", help="ZIP · DXF · 폴더")
    ap.add_argument("-f", "--format", choices=("md", "json", "both"), default="md")
    ap.add_argument("-o", "--out", help="출력 파일 경로(확장자 제외 가능). 없으면 표준출력")
    ap.add_argument("--config", help="설정 JSON (공사방법·보정계수·전압강하 유형 등)")
    ap.add_argument("--fail-on", choices=("error", "warning", "never"), default="never",
                    help="해당 등급 이상이 있으면 종료코드 1")
    ap.add_argument("--version", action="version", version="dxfcheck " + __version__)
    args = ap.parse_args(argv)

    try:
        settings = Settings.load(args.config)
    except (OSError, ValueError) as exc:
        print("설정 오류: %s" % exc, file=sys.stderr)
        return 2
    report = analyze_paths(args.inputs, settings)

    outputs = []
    if args.format in ("md", "both"):
        outputs.append((".md", to_markdown(report)))
    if args.format in ("json", "both"):
        outputs.append((".json", to_json(report)))

    if args.out:
        base = Path(args.out)
        if base.suffix.lower() in (".md", ".json"):
            base = base.with_suffix("")
        base.parent.mkdir(parents=True, exist_ok=True)
        for ext, text in outputs:
            p = base.with_suffix(ext)
            p.write_text(text, encoding="utf-8")
            print("저장: %s" % p, file=sys.stderr)
    else:
        sys.stdout.write("\n".join(text for _, text in outputs))

    if args.fail_on == "error" and report.total(Severity.ERROR):
        return 1
    if args.fail_on == "warning" and (report.total(Severity.ERROR) or report.total(Severity.WARNING)):
        return 1
    return 0
