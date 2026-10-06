"""검증 결과 모델."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Severity(str, Enum):
    ERROR = "error"      # 부적합 — 규정 위반 또는 도면을 쓸 수 없는 결함
    WARNING = "warning"  # 주의 — 위반 가능성, 확인 필요
    INFO = "info"        # 참고 — 권고·검토 한계

    @property
    def label(self) -> str:
        return {"error": "부적합", "warning": "주의", "info": "참고"}[self.value]


class Category(str, Enum):
    FILE = "파일·구조"
    CAD = "CAD 품질"
    DOC = "도면 표기"
    KEC = "KEC 전기"
    SET = "도면 세트 정합성"
    PROFILE = "학습 기준 비교"
    LLM = "미인식 표기 (LLM)"


@dataclass
class Finding:
    rule_id: str
    category: Category
    severity: Severity
    title: str
    message: str
    reference: str = ""                       # 근거 조항 (예: KEC 212.4.1)
    location: Dict[str, Any] = field(default_factory=dict)  # layer, layout, handle, x, y
    evidence: List[str] = field(default_factory=list)       # 원문 텍스트 등

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["category"] = self.category.value
        d["severity"] = self.severity.value
        return d


@dataclass
class CircuitRow:
    """차단기 ↔ 전선 대조 결과 한 줄 (보고서 표)."""

    breaker: str
    cable: str
    in_a: Optional[float]
    iz_a: Optional[float]
    result: str          # 적합 / 부적합 / 주의 / 판정불가
    basis: str           # 연관 근거 (같은 문자 / 같은 행 / 근접)
    note: str = ""


@dataclass
class FileReport:
    path: str                      # 압축 내부 경로 또는 입력 경로
    kind: str                      # dxf / dwg / other
    findings: List[Finding] = field(default_factory=list)
    overview: Dict[str, Any] = field(default_factory=dict)
    circuits: List[CircuitRow] = field(default_factory=list)

    def count(self, sev: Severity) -> int:
        return sum(1 for f in self.findings if f.severity == sev)

    @property
    def score(self) -> int:
        s = 100 - 15 * self.count(Severity.ERROR) - 4 * self.count(Severity.WARNING)
        return max(0, s)

    @property
    def verdict(self) -> str:
        if self.kind != "dxf":
            return "검증 불가"
        if any(f.severity == Severity.ERROR and f.category == Category.FILE for f in self.findings):
            return "검증 불가"
        if self.count(Severity.ERROR):
            return "부적합"
        if self.count(Severity.WARNING):
            return "조건부 적합"
        return "적합"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "kind": self.kind,
            "verdict": self.verdict,
            "score": self.score,
            "counts": {s.value: self.count(s) for s in Severity},
            "overview": self.overview,
            "circuits": [asdict(c) for c in self.circuits],
            "findings": [f.to_dict() for f in self.findings],
        }


@dataclass
class PackageReport:
    """도면 세트(한 입력 ZIP/폴더) 검증 결과."""

    name: str
    sheets: List[Dict[str, Any]] = field(default_factory=list)       # 도면번호·파일·도면명·근거
    facts: Dict[str, Dict[str, str]] = field(default_factory=dict)   # 사실 → {도면번호: 값}
    metadata: Dict[str, Any] = field(default_factory=dict)
    findings: List[Finding] = field(default_factory=list)
    profile: Dict[str, Any] = field(default_factory=dict)

    def count(self, sev: Severity) -> int:
        return sum(1 for f in self.findings if f.severity == sev)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "sheets": self.sheets, "facts": self.facts, "metadata": self.metadata,
                "profile": self.profile, "findings": [f.to_dict() for f in self.findings]}


@dataclass
class Report:
    inputs: List[str]
    files: List[FileReport] = field(default_factory=list)
    archive_findings: List[Finding] = field(default_factory=list)
    packages: List[PackageReport] = field(default_factory=list)
    llm: Dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""
    settings: Dict[str, Any] = field(default_factory=dict)

    @property
    def dxf_files(self) -> List[FileReport]:
        return [f for f in self.files if f.kind == "dxf"]

    def total(self, sev: Severity) -> int:
        return (sum(f.count(sev) for f in self.files)
                + sum(1 for f in self.archive_findings if f.severity == sev)
                + sum(p.count(sev) for p in self.packages))

    @property
    def verdict(self) -> str:
        dxf = self.dxf_files
        if not dxf:
            return "검증 불가"
        verdicts = {f.verdict for f in dxf}
        if any(p.count(Severity.ERROR) for p in self.packages):
            verdicts.add("부적합")
        elif any(p.count(Severity.WARNING) for p in self.packages):
            verdicts.add("조건부 적합")
        for v in ("부적합", "검증 불가", "조건부 적합"):
            if v in verdicts:
                return v
        return "적합"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "inputs": self.inputs,
            "generated_at": self.generated_at,
            "verdict": self.verdict,
            "counts": {s.value: self.total(s) for s in Severity},
            "archive_findings": [f.to_dict() for f in self.archive_findings],
            "packages": [p.to_dict() for p in self.packages],
            "llm": self.llm,
            "files": [f.to_dict() for f in self.files],
            "settings": self.settings,
        }
