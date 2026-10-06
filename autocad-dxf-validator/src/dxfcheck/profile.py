"""기준 도면 학습(프로파일) — 승인된 CAD 도면에서 '정상 도면의 모습'을 배우고 새 도면과 비교한다.

학습은 통계 프로파일이다(신경망·LLM 학습이 아님). 판정 근거를 사람이 그대로 읽을 수 있도록
도면번호별로 다음을 센다.
  - 레이어 · 문자 스타일(글꼴) · 블록 이름 · 표제란 속성 태그의 출현 빈도
  - 표준 문구(숫자 없는 단어) 출현 빈도
  - 추출된 사실 항목(설비용량·직병렬·퓨즈 …)의 존재 빈도
  - 객체 수 · 문자 수 범위
  - 세트에 포함된 도면번호 빈도
여러 번 학습하면 누적된다(`dxfcheck learn 새기준.zip --profile 기존.json`).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Union

from .drawingset import Sheet
from .model import Category, Finding, Severity

P = Category.PROFILE
VERSION = 1
_TOKEN = re.compile(r"[가-힣A-Z][가-힣A-Z\-/()]{1,30}")
_REQUIRED = 0.8    # 기준 도면 80% 이상에 있던 항목은 '있어야 할 것'


def tokens(sheet: Sheet) -> set:
    out = set()
    for t in sheet.drawing.texts:
        for tok in _TOKEN.findall(t.norm):
            if not any(ch.isdigit() for ch in tok) and len(tok) >= 2:
                out.add(tok)
    return out


@dataclass
class SheetProfile:
    n: int = 0
    layers: Counter = field(default_factory=Counter)
    styles: Counter = field(default_factory=Counter)
    fonts: Counter = field(default_factory=Counter)
    blocks: Counter = field(default_factory=Counter)
    attr_tags: Counter = field(default_factory=Counter)
    tokens: Counter = field(default_factory=Counter)
    facts: Counter = field(default_factory=Counter)
    entities: List[int] = field(default_factory=list)
    texts: List[int] = field(default_factory=list)

    def add(self, s: Sheet) -> None:
        d = s.drawing
        self.n += 1
        self.layers.update({k for k, v in d.layer_count.items() if v})
        used_styles = {t.style.upper() for t in d.texts}
        self.styles.update(used_styles)
        self.fonts.update({(d.styles.get(st, ("", ""))[0] or "").upper() for st in used_styles} - {""})
        self.blocks.update(set(d.blocks_used))
        self.attr_tags.update({tag for _, attrs, _ in d.inserts_attribs for tag in attrs})
        self.tokens.update(tokens(s))
        self.facts.update(set(s.facts))
        self.entities.append(d.total_entities)
        self.texts.append(len(d.texts))

    def to_dict(self) -> dict:
        return {k: (dict(v) if isinstance(v, Counter) else v) for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, data: dict) -> "SheetProfile":
        p = cls()
        for k, v in data.items():
            setattr(p, k, Counter(v) if isinstance(getattr(p, k), Counter) else v)
        return p


@dataclass
class Profile:
    sets: int = 0
    sources: List[str] = field(default_factory=list)
    set_numbers: Counter = field(default_factory=Counter)
    sheets: Dict[str, SheetProfile] = field(default_factory=dict)
    all_layers: Counter = field(default_factory=Counter)

    def learn_set(self, source: str, sheets: Iterable[Sheet]) -> int:
        sheets = list(sheets)
        self.sets += 1
        self.sources.append(source)
        self.set_numbers.update({s.no for s in sheets if s.no})
        n = 0
        for s in sheets:
            key = s.no or "_UNNUMBERED"
            self.sheets.setdefault(key, SheetProfile()).add(s)
            self.all_layers.update({k for k, v in s.drawing.layer_count.items() if v})
            n += 1
        return n

    # ── 저장 ──
    def save(self, path: Union[str, Path]) -> None:
        data = {"version": VERSION, "sets": self.sets, "sources": self.sources,
                "set_numbers": dict(self.set_numbers), "all_layers": dict(self.all_layers),
                "sheets": {k: v.to_dict() for k, v in sorted(self.sheets.items())}}
        Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Union[str, Path, None]) -> Optional["Profile"]:
        if not path or not Path(path).exists():
            return None
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") != VERSION:
            raise ValueError("프로파일 버전이 맞지 않습니다: %s" % data.get("version"))
        p = cls(sets=data["sets"], sources=data["sources"], set_numbers=Counter(data["set_numbers"]),
                all_layers=Counter(data["all_layers"]))
        p.sheets = {k: SheetProfile.from_dict(v) for k, v in data["sheets"].items()}
        return p

    def summary(self) -> Dict[str, object]:
        return {"학습 세트": self.sets, "학습 도면": sum(s.n for s in self.sheets.values()),
                "도면번호": ", ".join("%s×%d" % (k, v.n) for k, v in sorted(self.sheets.items()))}


# ── 비교 ────────────────────────────────────────────────────────────────
def _sev(n: int) -> Severity:
    """기준 샘플이 3개 이상이면 '주의', 적으면 '참고'로 낮춘다."""
    return Severity.WARNING if n >= 3 else Severity.INFO


def _required(c: Counter, n: int) -> List[str]:
    return [k for k, v in c.items() if v / max(1, n) >= _REQUIRED]


def compare_sheet(profile: Profile, s: Sheet) -> List[Finding]:
    out: List[Finding] = []
    key = s.no or "_UNNUMBERED"
    sp = profile.sheets.get(key)
    if sp is None:
        if s.no:
            out.append(Finding("PRF-000", P, Severity.INFO, "학습되지 않은 도면번호",
                               "%s 도면은 학습 기준이 없어 학습 비교를 하지 않았습니다." % s.no))
        return out
    d = s.drawing
    base = "기준 도면 %d개 학습" % sp.n
    sev = _sev(sp.n)

    layers = {k for k, v in d.layer_count.items() if v}
    new_layers = sorted(l for l in layers if profile.all_layers.get(l, 0) == 0)
    if new_layers:
        out.append(Finding("PRF-001", P, Severity.WARNING if profile.sets >= 2 else Severity.INFO,
                           "비표준(미학습) 레이어",
                           "학습한 어떤 기준 도면에도 없던 레이어 %d개를 사용했습니다." % len(new_layers),
                           base, evidence=new_layers[:15]))
    missing = sorted(set(_required(sp.layers, sp.n)) - layers)
    if missing:
        out.append(Finding("PRF-002", P, sev, "표준 레이어 누락",
                           "기준 도면에 늘 있던 레이어가 없습니다.", base, evidence=missing[:15]))

    used_styles = {t.style.upper() for t in d.texts}
    fonts = {(d.styles.get(st, ("", ""))[0] or "").upper() for st in used_styles} - {""}
    new_fonts = sorted(f for f in fonts if sp.fonts.get(f, 0) == 0)
    if new_fonts and sp.fonts:
        out.append(Finding("PRF-003", P, sev, "미학습 글꼴",
                           "기준 도면에 없던 글꼴을 사용했습니다(한글·㎟ 깨짐 확인).", base, evidence=new_fonts))

    tags = {tag for _, attrs, _ in d.inserts_attribs for tag in attrs}
    miss_tags = sorted(set(_required(sp.attr_tags, sp.n)) - tags)
    if miss_tags:
        out.append(Finding("PRF-004", P, sev, "표제란 속성 누락",
                           "기준 도면 표제란에 늘 있던 속성이 없습니다.", base, evidence=miss_tags))
    miss_blocks = sorted(set(_required(sp.blocks, sp.n)) - set(d.blocks_used))
    if miss_blocks:
        out.append(Finding("PRF-004", P, sev, "표준 블록 누락",
                           "기준 도면에 늘 있던 블록(심볼·표제란)이 없습니다.", base, evidence=miss_blocks[:15]))

    toks = tokens(s)
    miss_tok = sorted(set(_required(sp.tokens, sp.n)) - toks)
    if miss_tok:
        out.append(Finding("PRF-005", P, sev, "표준 문구 누락",
                           "기준 도면에 늘 있던 문구 %d개가 없습니다. 항목이 빠졌거나 표기가 바뀌었는지 확인하세요." % len(miss_tok),
                           base, evidence=miss_tok[:15]))
    miss_fact = sorted(set(_required(sp.facts, sp.n)) - set(s.facts))
    if miss_fact:
        out.append(Finding("PRF-006", P, sev, "설계 수치 표기 누락",
                           "기준 도면에서 늘 읽히던 설계 항목을 이 도면에서 찾지 못했습니다.", base,
                           evidence=[FACT_LABEL.get(f, f) for f in miss_fact]))

    for label, values, cur in (("객체 수", sp.entities, d.total_entities), ("문자 수", sp.texts, len(d.texts))):
        if not values:
            continue
        lo, hi = min(values), max(values)
        if cur < 0.5 * lo or cur > 2.0 * max(hi, 1):
            out.append(Finding("PRF-007", P, sev, "%s 이상치" % label,
                               "%s %d — 기준 범위 %d~%d를 크게 벗어났습니다(누락·중복 생성 의심)." % (label, cur, lo, hi), base))
    return out


def compare_set(profile: Profile, sheets: List[Sheet]) -> List[Finding]:
    present = {s.no for s in sheets if s.no}
    expected = sorted(k for k, v in profile.set_numbers.items() if v / max(1, profile.sets) >= _REQUIRED)
    missing = [n for n in expected if n not in present]
    out = []
    if missing:
        out.append(Finding("PRF-010", P, _sev(profile.sets), "학습 세트 대비 도면 누락",
                           "기준 세트에 늘 있던 도면이 없습니다: %s" % ", ".join(missing),
                           "기준 세트 %d개 학습" % profile.sets, evidence=missing))
    return out


FACT_LABEL = {
    "capacity_kw": "설비용량(kW)", "module_count": "모듈 수량", "module_w": "모듈 출력(W)",
    "inverter_count": "인버터 수량", "inverter_kw": "인버터 용량", "series": "직렬 수", "parallel": "병렬 수",
    "dc_fuse_a": "DC 퓨즈(A)", "mppt": "MPPT 수", "mppt_channel": "MPPT 채널", "dc_sq": "DC 케이블 단면적",
    "ac_sq": "AC 케이블 단면적", "mccb_at": "차단기 AT", "mccb_af": "차단기 AF", "receiving": "수전 방식",
    "install_type": "설치 형태", "tray_type": "트레이 유형", "string_vmax": "최대 스트링 전압",
    "inverter_vmax": "인버터 최대입력전압",
}
