"""명령행.

  dxfcheck <ZIP|DXF|폴더>... [-f md|json|both] [-o 출력] [--config 설정.json] [--profile 학습.json]
  dxfcheck learn <기준 ZIP|DXF|폴더>... --profile 학습.json     (기존 프로파일에 누적)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .analyzer import analyze_paths, learn_paths
from .config import Settings
from .model import Severity
from .profile import Profile
from .report import to_json, to_markdown


def _learn(argv: List[str]) -> int:
    ap = argparse.ArgumentParser(prog="dxfcheck learn", description="승인된 기준 도면으로 검증 기준(프로파일) 학습")
    ap.add_argument("inputs", nargs="+", help="기준 ZIP · DXF · 폴더 (ZIP 하나 = 도면 세트 하나)")
    ap.add_argument("--profile", required=True, help="프로파일 JSON (있으면 누적 학습)")
    ap.add_argument("--reset", action="store_true", help="기존 프로파일을 무시하고 새로 학습")
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    try:
        settings = Settings.load(args.config)
        prof = None if args.reset else Profile.load(args.profile)
    except (OSError, ValueError) as exc:
        print("설정/프로파일 오류: %s" % exc, file=sys.stderr)
        return 2
    prof, log = learn_paths(args.inputs, settings, prof)
    Path(args.profile).parent.mkdir(parents=True, exist_ok=True)
    prof.save(args.profile)
    for line in log:
        print(line)
    print("저장: %s — %s" % (args.profile, " · ".join("%s %s" % kv for kv in prof.summary().items())))
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "learn":
        return _learn(argv[1:])
    ap = argparse.ArgumentParser(prog="dxfcheck", description="AutoCAD DXF 도면 검증 (KEC · 도면 세트 · 학습 기준)")
    ap.add_argument("inputs", nargs="+", help="ZIP · DXF · 폴더")
    ap.add_argument("-f", "--format", choices=("md", "json", "both"), default="md")
    ap.add_argument("-o", "--out", help="출력 파일 경로(확장자 제외 가능). 없으면 표준출력")
    ap.add_argument("--config", help="설정 JSON (공사방법·보정계수·전압강하 유형·회사명 등)")
    ap.add_argument("--profile", help="학습 프로파일 JSON (dxfcheck learn 으로 생성)")
    ap.add_argument("--fail-on", choices=("error", "warning", "never"), default="never",
                    help="해당 등급 이상이 있으면 종료코드 1")
    ap.add_argument("--version", action="version", version="dxfcheck " + __version__)
    args = ap.parse_args(argv)

    try:
        settings = Settings.load(args.config)
        profile = Profile.load(args.profile) if args.profile else None
    except (OSError, ValueError) as exc:
        print("설정/프로파일 오류: %s" % exc, file=sys.stderr)
        return 2
    if args.profile and profile is None:
        print("프로파일이 없습니다: %s (dxfcheck learn 으로 먼저 학습)" % args.profile, file=sys.stderr)
        return 2
    report = analyze_paths(args.inputs, settings, profile=profile)

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
