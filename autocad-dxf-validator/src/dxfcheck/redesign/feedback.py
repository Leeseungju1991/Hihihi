"""재설계 피드백 학습 저장소.

같은 '지적 유형 + 원문 패턴'에 대해
  - 사람이 남긴 피드백: accept(수정안 승인) / reject(이 수정은 하지 말 것) / correct(이렇게 고쳐라: 수정 문자)
  - 자동 결과: 재검증에서 해소됨(ok) / 해소 안 됨·회귀(fail)
을 누적한다. 다음 재설계에서
  1) correct  → 학습된 수정으로 바로 적용(LLM 호출 없이, confidence=memory)
  2) reject 또는 실패만 2회 이상 → 그 수정은 다시 제안하지 않음
  3) correct·성공 사례 → LLM 수정 프롬프트의 예시(few-shot)로 사용
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union

from ..drawing import normalize
from ..model import Finding

_NUM = re.compile(r"\d+(?:\.\d+)?")


def pattern_of(f: Finding, text: str = "") -> str:
    """지적 대상 원문을 정규화한 패턴. 숫자는 그대로 둔다(같은 표기에만 같은 수정)."""
    base = text or (f.evidence[0] if f.evidence else "")
    return normalize(base)[:200]


@dataclass
class Entry:
    rule_id: str
    pattern: str
    decision: str = ""            # accept / reject / correct / "" (자동 결과만)
    correction: str = ""          # correct 일 때 바꿀 문자 전체
    note: str = ""
    ok: int = 0
    fail: int = 0
    last_before: str = ""
    last_after: str = ""
    updated: str = ""


@dataclass
class FeedbackStore:
    path: Optional[Path] = None
    entries: Dict[str, Entry] = field(default_factory=dict)

    @staticmethod
    def key(rule_id: str, pattern: str) -> str:
        return "%s||%s" % (rule_id, pattern)

    @classmethod
    def load(cls, path: Union[str, Path, None]) -> "FeedbackStore":
        st = cls(path=Path(path) if path else None)
        if st.path and st.path.exists():
            data = json.loads(st.path.read_text(encoding="utf-8"))
            for e in data.get("entries", []):
                en = Entry(**e)
                st.entries[cls.key(en.rule_id, en.pattern)] = en
        return st

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {"version": 1, "entries": [asdict(e) for e in self.entries.values()]}
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def _get(self, rule_id: str, pattern: str) -> Entry:
        k = self.key(rule_id, pattern)
        if k not in self.entries:
            self.entries[k] = Entry(rule_id=rule_id, pattern=pattern)
        return self.entries[k]

    # ── 사람 피드백 ──
    def record(self, rule_id: str, pattern: str, decision: str, correction: str = "", note: str = "") -> Entry:
        if decision not in ("accept", "reject", "correct"):
            raise ValueError("decision 은 accept / reject / correct")
        if decision == "correct" and not correction.strip():
            raise ValueError("correct 에는 correction(수정 문자)이 필요합니다")
        e = self._get(rule_id, pattern)
        e.decision, e.correction, e.note = decision, correction.strip(), note
        e.updated = _dt.datetime.now().isoformat(timespec="seconds")
        return e

    # ── 자동 결과 ──
    def result(self, rule_id: str, pattern: str, ok: bool, before: str = "", after: str = "") -> None:
        e = self._get(rule_id, pattern)
        if ok:
            e.ok += 1
            e.last_before, e.last_after = before, after
        else:
            e.fail += 1
        e.updated = _dt.datetime.now().isoformat(timespec="seconds")

    # ── 조회 ──
    def lookup(self, rule_id: str, pattern: str) -> Optional[Entry]:
        return self.entries.get(self.key(rule_id, pattern))

    def blocked(self, rule_id: str, pattern: str) -> bool:
        e = self.lookup(rule_id, pattern)
        return bool(e and (e.decision == "reject" or (e.fail >= 2 and e.ok == 0 and e.decision != "correct")))

    def correction(self, rule_id: str, pattern: str) -> str:
        e = self.lookup(rule_id, pattern)
        return e.correction if e and e.decision == "correct" else ""

    def examples(self, rule_id: str, limit: int = 3) -> List[Dict[str, str]]:
        """LLM 수정 프롬프트용 예시: 사람이 고친 것 → 재검증에서 해소된 것 순."""
        out: List[Dict[str, str]] = []
        es = [e for e in self.entries.values() if e.rule_id == rule_id]
        for e in sorted(es, key=lambda x: (x.decision != "correct", -x.ok)):
            if e.decision == "correct":
                out.append({"before": e.pattern, "after": e.correction, "by": "사람"})
            elif e.ok and e.last_after:
                out.append({"before": e.last_before, "after": e.last_after, "by": "재검증 통과"})
            if len(out) >= limit:
                break
        return out
