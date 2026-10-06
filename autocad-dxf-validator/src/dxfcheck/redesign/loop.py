"""재설계 루프: 검증 → 수정안 → 적용 → 재검증(회귀 확인·되돌림) → 학습 → 반복 → ZIP.

수정안 우선순위
  1. 학습된 수정(사람이 correct 로 남긴 문자)        confidence=memory
  2. 규칙 수정안(Finding.fix, 공식으로 계산)          confidence=rule / majority
  3. LLM 문자 수정안(규칙이 못 고친 지적만, 가드 통과) confidence=llm
  4. 도면 생성기 재실행(regenerate) — regenerator 훅이 있으면 호출, 없으면 '수동 조치'로 반환
재검증에서 새 '부적합'이 생긴 파일은 그 라운드 변경을 되돌리고 실패로 학습한다.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

from ezdxf import recover

from ..analyzer import analyze_paths
from ..archive import extract_zip
from ..config import Settings
from ..llm import LLMSession
from ..model import Category, Finding, Report, Severity
from ..profile import Profile
from ..report import to_json, to_markdown
from . import llm_fix
from .feedback import FeedbackStore, pattern_of
from .fixes import Change, apply_ops, get_text

Regenerator = Callable[[List[dict], Path], List[str]]   # (재생성 요청, 작업 폴더) → 바뀐 파일 목록
_SKIP_CATS = (Category.FILE, Category.LLM, Category.PROFILE)


def _sig(f: Finding) -> str:
    return "%s|%s|%s|%s" % (f.file, f.rule_id, f.title.replace(" (LLM 해석)", ""), f.location.get("handle", ""))


def _targets(r: Report) -> List[Finding]:
    return [f for f in r.all_findings() if f.severity in (Severity.ERROR, Severity.WARNING)
            and f.category not in _SKIP_CATS]


def _counts(r: Report) -> Dict[str, int]:
    return {s.value: r.total(s) for s in Severity}


def _summary(r: Report) -> dict:
    return {"verdict": r.verdict, "counts": _counts(r),
            "items21": r.packages[0].items21 if r.packages else []}


@dataclass
class RoundLog:
    round: int
    applied: int = 0
    failed: int = 0
    reverted: int = 0
    llm_proposals: int = 0
    regenerated: List[str] = field(default_factory=list)
    errors_before: int = 0
    errors_after: int = 0
    warnings_before: int = 0
    warnings_after: int = 0
    resolved: List[str] = field(default_factory=list)      # 해소된 지적 제목
    new_errors: List[str] = field(default_factory=list)    # 회귀(새 부적합)


@dataclass
class RedesignResult:
    status: str                       # 통과 / 개선 / 미해결 / 변경 없음
    rounds: List[RoundLog]
    before: Report
    after: Report
    changes: List[Change]
    manual: List[dict]                # 자동 수정 못 한 지적 (사유 포함)
    zip_path: Optional[Path] = None
    work_dir: Optional[Path] = None

    def to_dict(self) -> dict:
        return {"status": self.status, "rounds": [r.__dict__ for r in self.rounds],
                "before": _summary(self.before), "after": _summary(self.after),
                "changes": [c.to_dict() for c in self.changes], "manual": self.manual,
                "zip": str(self.zip_path) if self.zip_path else None,
                "after_report": self.after.to_dict()}


def prepare(input_path: Union[str, Path], work_dir: Path, settings: Settings) -> Path:
    """입력을 work_dir/original 로 풀고 work_dir/working 사본을 만든다."""
    src = Path(input_path)
    orig, working = work_dir / "original", work_dir / "working"
    for d in (orig, working):
        if d.exists():
            shutil.rmtree(d)
    orig.mkdir(parents=True)
    if src.is_dir():
        shutil.copytree(src, orig, dirs_exist_ok=True)
    elif src.suffix.lower() == ".zip":
        extract_zip(src, orig, settings)
    else:
        shutil.copy2(src, orig / src.name)
    shutil.copytree(orig, working)
    return working


class _Texts:
    """작업 파일의 현재 문자 읽기(라운드 단위 캐시)."""

    def __init__(self, root: Path):
        self.root, self.docs = root, {}

    def get(self, file: str, handle: str) -> Optional[str]:
        if file not in self.docs:
            try:
                self.docs[file] = recover.readfile(str(self.root / file))[0]
            except Exception:  # noqa: BLE001
                self.docs[file] = None
        doc = self.docs[file]
        e = doc.entitydb.get(handle) if doc is not None and handle else None
        return get_text(e) if e is not None else None


def finding_pattern(f: Finding, root: Path, texts: Optional["_Texts"] = None) -> str:
    """학습 키 패턴: 지적 위치 문자(현재 DXF 내용) 기준. API 피드백과 재설계 루프가 같은 값을 쓴다."""
    texts = texts or _Texts(root)
    handle = str(f.location.get("handle", ""))
    cur = texts.get(f.file, handle) if (f.file and handle) else None
    return pattern_of(f, cur or "")


def _op_key(op: dict) -> str:
    return json.dumps({k: v for k, v in op.items() if k != "_meta"}, sort_keys=True, ensure_ascii=False)


def redesign(input_path: Union[str, Path], settings: Optional[Settings] = None, *,
             out_zip: Union[str, Path, None] = None, work_dir: Union[str, Path, None] = None,
             profile: Optional[Profile] = None, llm: Optional[LLMSession] = None,
             fix_complete: Optional[llm_fix.Complete] = None, feedback: Optional[FeedbackStore] = None,
             max_rounds: int = 3, regenerator: Optional[Regenerator] = None,
             initial: Optional[Report] = None) -> RedesignResult:
    settings = settings or Settings()
    feedback = feedback or FeedbackStore()
    wd = Path(work_dir) if work_dir else Path(tempfile.mkdtemp(prefix="dxfcheck_redesign_"))
    working = prepare(input_path, wd, settings)

    def check() -> Report:
        return analyze_paths([working], settings, profile=profile, llm=llm)

    before = check()
    report = before
    changes: List[Change] = []
    rounds: List[RoundLog] = []
    applied_keys: set = set()
    llm_tried: set = set()
    manual: Dict[str, dict] = {}
    regen_done: set = set()

    for rnd in range(1, max_rounds + 1):
        log = RoundLog(rnd, errors_before=report.total(Severity.ERROR), warnings_before=report.total(Severity.WARNING))
        if log.errors_before == 0 and log.warnings_before == 0:
            break
        texts = _Texts(working)
        by_file: Dict[str, List[dict]] = {}
        regen: List[dict] = []
        sig_of_id: Dict[str, Tuple[str, str, str]] = {}   # finding_id → (sig, rule, pattern)
        llm_budget = settings.redesign_llm_max
        claimed: Dict[Tuple[str, str], str] = {}   # (파일, handle) → 이번 라운드에 고치는 지적 id

        for f in _targets(report):
            handle = str(f.location.get("handle", ""))
            cur = texts.get(f.file, handle) if (f.file and handle) else None
            pat = finding_pattern(f, working, texts)
            sig_of_id[f.id] = (_sig(f), f.rule_id, pat)
            meta = {"finding_id": f.id, "rule_id": f.rule_id}
            if feedback.blocked(f.rule_id, pat):
                manual[f.id] = _manual(f, "피드백 거부 또는 반복 실패로 자동 수정 중단")
                continue
            ops: List[dict] = []
            corr = feedback.correction(f.rule_id, pat)
            if corr and cur is not None:
                ops = [{"op": "set_text", "file": f.file, "handle": handle, "value": corr,
                        "_meta": dict(meta, reason="학습된 수정(사람 피드백)", confidence="memory")}]
            elif f.fix.get("ops"):
                for op in f.fix["ops"]:
                    if op["op"] == "regenerate":
                        if _op_key(op) not in regen_done:
                            regen.append(dict(op, finding_id=f.id, reason=f.fix.get("reason", "")))
                        continue
                    ops.append(dict(op, file=op.get("file") or f.file,
                                    _meta=dict(meta, reason=f.fix.get("reason", ""),
                                               confidence=f.fix.get("confidence", "rule"))))
                if not ops and not regen:
                    manual[f.id] = _manual(f, "도면 생성기 재실행 필요: " + f.fix.get("reason", ""))
            elif fix_complete is not None and cur is not None and f.id not in llm_tried and llm_budget > 0:
                llm_tried.add(f.id)
                llm_budget -= 1
                log.llm_proposals += 1
                res = llm_fix.propose(fix_complete, f, cur, feedback)
                if "new_text" in res:
                    ops = [{"op": "set_text", "file": f.file, "handle": handle, "value": res["new_text"],
                            "_meta": dict(meta, reason="LLM 수정안: " + res.get("reason", ""), confidence="llm")}]
                else:
                    manual[f.id] = _manual(f, res["error"])
            else:
                manual.setdefault(f.id, _manual(f, "자동 수정안 없음 (문자 위치 없음 또는 LLM 꺼짐)"))
            # 같은 문자를 한 라운드에 두 지적이 고치지 않는다(다음 라운드 재검증이 다시 계산)
            if any(claimed.get((op["file"], str(op.get("handle", "")))) not in (None, f.id)
                   for op in ops if op.get("handle")):
                continue
            for op in ops:
                k = _op_key(op)
                if k in applied_keys:
                    continue
                applied_keys.add(k)
                if op.get("handle"):
                    claimed[(op["file"], str(op["handle"]))] = f.id
                by_file.setdefault(op["file"], []).append(op)
                manual.pop(f.id, None)

        # 적용 (파일별 백업 후)
        backups: Dict[str, Path] = {}
        round_changes: List[Change] = []
        for file, ops in by_file.items():
            p = working / file
            if not p.exists():
                continue
            bak = wd / "backup" / ("r%d" % rnd) / file
            bak.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, bak)
            backups[file] = bak
            for op in ops:
                op.setdefault("file", file)
            res = apply_ops(p, ops, {})
            for c in res:
                c.file = file
            round_changes += res
        if regen:
            if regenerator is not None:
                changed = regenerator([{k: v for k, v in r.items()} for r in regen], working) or []
                log.regenerated = list(changed)
                regen_done |= {_op_key({k: v for k, v in r.items() if k not in ("finding_id", "reason")}) for r in regen}
            else:
                for r in regen:
                    manual[r["finding_id"]] = {"finding_id": r["finding_id"], "rule_id": "", "title": r.get("reason", ""),
                                               "why": "도면 생성기(SolarAutoDesign) 재실행 필요", "regenerate": r}
        log.applied = sum(c.ok for c in round_changes)
        log.failed = sum(not c.ok for c in round_changes)
        changes += round_changes
        if not log.applied and not log.regenerated:
            log.errors_after, log.warnings_after = log.errors_before, log.warnings_before
            rounds.append(log)
            break

        new_report = check()
        # 회귀: 새로 생긴 '부적합'이 수정한 파일에 있으면 그 파일을 되돌린다
        old_err = {_sig(f) for f in report.all_findings() if f.severity == Severity.ERROR}
        new_err = [f for f in new_report.all_findings() if f.severity == Severity.ERROR and _sig(f) not in old_err]
        touched = {c.file for c in round_changes if c.ok}
        revert_files = set()
        for f in new_err:
            files = {f.file} | {op.get("file", "") for op in f.fix.get("ops", [])}
            hit = files & touched
            if hit:
                revert_files |= hit
            log.new_errors.append("%s — %s" % (f.title, f.file))
        for file in revert_files:
            shutil.copy2(backups[file], working / file)
            for c in round_changes:
                if c.file == file and c.ok:
                    c.reverted = True
                    log.reverted += 1
        if revert_files:
            new_report = check()

        # 학습: 수정한 지적이 해소됐는가
        after_sigs = {_sig(f) for f in new_report.all_findings() if f.severity in (Severity.ERROR, Severity.WARNING)}
        seen = set()
        for c in round_changes:
            if not c.ok or c.finding_id in seen or c.finding_id not in sig_of_id:
                continue
            seen.add(c.finding_id)
            sig, rule, pat = sig_of_id[c.finding_id]
            ok = (sig not in after_sigs) and not c.reverted
            feedback.result(rule, pat, ok, c.before, c.after)
            if ok:
                log.resolved.append(sig.split("|")[2])
        log.errors_after = new_report.total(Severity.ERROR)
        log.warnings_after = new_report.total(Severity.WARNING)
        rounds.append(log)
        progressed = (log.errors_after, log.warnings_after) < (log.errors_before, log.warnings_before)
        report = new_report
        if log.errors_after == 0 or not progressed:
            break

    feedback.save()
    after = report
    # 남은 지적 중 수동 목록에 없는 것도 반환
    remaining = {f.id: f for f in _targets(after)}
    manual_out = [m for fid, m in manual.items() if fid in remaining or m.get("regenerate")]
    for fid, f in remaining.items():
        if fid not in manual:
            manual_out.append(_manual(f, "재검증 후에도 남음"))
    e0, e1 = before.total(Severity.ERROR), after.total(Severity.ERROR)
    w0, w1 = before.total(Severity.WARNING), after.total(Severity.WARNING)
    if not any(c.ok and not c.reverted for c in changes) and not any(r.regenerated for r in rounds):
        status = "통과" if e0 == 0 else "변경 없음"
    elif e1 == 0:
        status = "통과"
    elif (e1, w1) < (e0, w0):
        status = "개선"
    else:
        status = "미해결"
    result = RedesignResult(status, rounds, before, after, changes, manual_out, work_dir=wd)
    if out_zip:
        result.zip_path = bundle(result, working, Path(out_zip))
    return result


def _manual(f: Finding, why: str) -> dict:
    return {"finding_id": f.id, "rule_id": f.rule_id, "title": f.title, "severity": f.severity.value,
            "file": f.file, "message": f.message, "why": why}


# ── ZIP ─────────────────────────────────────────────────────────────────
def summary_markdown(r: RedesignResult) -> str:
    b, a = r.before, r.after
    out = ["# 재설계 결과", "",
           "- 상태: **%s**" % r.status,
           "- 재설계 전: %s — 부적합 %d · 주의 %d" % (b.verdict, b.total(Severity.ERROR), b.total(Severity.WARNING)),
           "- 재설계 후: %s — 부적합 %d · 주의 %d" % (a.verdict, a.total(Severity.ERROR), a.total(Severity.WARNING)),
           "", "## 라운드", "", "| 라운드 | 적용 | 실패 | 되돌림 | LLM 제안 | 부적합 전→후 | 주의 전→후 | 회귀 |", "|---|---|---|---|---|---|---|---|"]
    for x in r.rounds:
        out.append("| %d | %d | %d | %d | %d | %d→%d | %d→%d | %s |" % (
            x.round, x.applied, x.failed, x.reverted, x.llm_proposals, x.errors_before, x.errors_after,
            x.warnings_before, x.warnings_after, "; ".join(x.new_errors) or "-"))
    out += ["", "## 변경 내역", "", "| 파일 | 규칙 | 근거 | 변경 전 | 변경 후 | 결과 |", "|---|---|---|---|---|---|"]
    for c in r.changes:
        res = "되돌림" if c.reverted else ("적용" if c.ok else "실패: " + c.detail)
        out.append("| %s | %s | %s | %s | %s | %s |" % (
            c.file, c.rule_id, c.confidence, c.before.replace("|", "\\|")[:60], c.after.replace("|", "\\|")[:60], res))
    if r.manual:
        out += ["", "## 수동 조치 필요", ""]
        out += ["- [%s] %s — %s" % (m.get("rule_id", ""), m.get("title", ""), m.get("why", "")) for m in r.manual]
    return "\n".join(out) + "\n"


def bundle(r: RedesignResult, working: Path, out_zip: Path) -> Path:
    """수정된 DXF + 전/후 보고서 + 변경 내역 ZIP."""
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(working.rglob("*")):
            if p.is_file():
                zf.write(p, "design/" + p.relative_to(working).as_posix())
        zf.writestr("reports/before.md", to_markdown(r.before))
        zf.writestr("reports/before.json", to_json(r.before))
        zf.writestr("reports/after.md", to_markdown(r.after))
        zf.writestr("reports/after.json", to_json(r.after))
        zf.writestr("reports/redesign.md", summary_markdown(r))
        zf.writestr("reports/redesign.json", json.dumps(
            {k: v for k, v in r.to_dict().items() if k != "after_report"}, ensure_ascii=False, indent=1))
    return out_zip


def validation_zip(report: Report, input_path: Union[str, Path], out_zip: Union[str, Path]) -> Path:
    """재설계 없이 검증만 한 경우의 다운로드: 원본 + 보고서."""
    out_zip = Path(out_zip)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    src = Path(input_path)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        if src.is_file():
            zf.write(src, "input/" + src.name)
        zf.writestr("reports/report.md", to_markdown(report))
        zf.writestr("reports/report.json", to_json(report))
    return out_zip


__all__: Sequence[str] = ("redesign", "prepare", "bundle", "validation_zip", "finding_pattern",
                          "RedesignResult", "Regenerator")
