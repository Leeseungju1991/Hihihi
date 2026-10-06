"""검증 설정. JSON 파일로 덮어쓸 수 있다 (`dxfcheck --config my.json`)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, Union


@dataclass
class Settings:
    # ── KEC 232.3.9 전압강하: "A" = 저압으로 수전(공공배전망 직접), "B" = 고압 이상 수전(사설 변압기)
    supply_type: str = "A"
    # ── 허용전류 (KEC 232.5 → KS C IEC 60364-5-52 부속서 B)
    cable_method: str = "C"     # 케이블 기본 공사방법 (C: 벽면 고정, 트레이도 보수적으로 C 적용)
    wire_method: str = "B1"     # 절연전선(HFIX·IV 등) 기본 공사방법 (B1: 전선관 내)
    derating: float = 1.0       # 주위온도·집합 보정계수 곱 (표기 없으면 1.0)
    power_factor: float = 0.9   # kW → 전류 환산 역률
    # ── 과부하 보호 I2 배율 (KEC 212.3.4 / 212.3.1) — 규약동작전류 = 배율 × In
    i2_factor: Dict[str, float] = field(default_factory=lambda: {
        "MCCB": 1.3, "ELB": 1.3, "ACB": 1.3, "NFB": 1.3, "CB": 1.3,
        "MCB": 1.45, "RCBO": 1.45, "FUSE": 1.6,
    })
    # ── 문자 연관 (차단기 텍스트 ↔ 전선 텍스트), 단위: 문자 높이 배수
    row_tolerance: float = 0.75     # 같은 행으로 보는 Y 차이
    row_max_distance: float = 120.0  # 같은 행 최대 X 거리
    near_radius: float = 25.0        # 행이 다를 때 근접 반경
    # ── CAD 품질
    min_text_height_mm: float = 2.5  # 출력 문자 최소 높이 (KS A ISO 3098 권장 2.5mm)
    layer0_ratio_warn: float = 0.3
    max_findings_per_rule: int = 30
    max_block_depth: int = 4
    # ── 압축 해제 한도
    max_archive_files: int = 3000
    max_archive_bytes: int = 2 * 1024 ** 3
    max_compression_ratio: int = 400
    max_archive_depth: int = 3

    @classmethod
    def load(cls, path: Union[str, Path, None]) -> "Settings":
        s = cls()
        if not path:
            return s
        data: Dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
        names = {f.name for f in fields(cls)}
        for k, v in data.items():
            if k not in names:
                raise ValueError("알 수 없는 설정 키: %s" % k)
            if k == "i2_factor":
                merged = dict(s.i2_factor)
                merged.update(v)
                v = merged
            setattr(s, k, v)
        if s.supply_type not in ("A", "B"):
            raise ValueError("supply_type 은 'A' 또는 'B' 이어야 합니다")
        return s

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
