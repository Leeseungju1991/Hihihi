"""검증 설정. JSON 파일로 덮어쓸 수 있다 (`dxfcheck --config my.json`)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Union


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
    # ── 도면 세트(E-01~E-21) 검증
    company_name: str = "에이치에너지"        # 표제란 회사명 (빈 문자열이면 검사 안 함)
    set_tolerance_pct: float = 0.5           # 도면 간·메타데이터 수치 허용 오차(%)
    dc_cable_min_sq: float = 6.0             # DC 케이블 최소 단면적 [확인 필요: 근거 명시]
    hardcode_suspects: List[str] = field(default_factory=lambda: ["70SQ", "100AT", "100A"])
    standard_layers: List[str] = field(default_factory=list)  # 비어 있으면 학습 프로파일 사용
    paper_size_mm: List[float] = field(default_factory=lambda: [420.0, 297.0])  # A3
    # 메타데이터 키 → 표준 사실명 (SolarAutoDesign 키 이름은 [미검증])
    meta_keys: Dict[str, List[str]] = field(default_factory=lambda: {
        "capacity_kw": ["as_designed_kw", "designed_kw"],   # p_pv_kw 는 '목표' 용량이라 기준으로 쓰지 않음
        "module_count": ["module_count", "n_modules", "modules"],
        "inverter_count": ["inverter_count", "n_inverters", "inverters"],
        "series": ["n_series", "series", "modules_per_string"],
        "parallel": ["n_parallel", "parallel", "strings"],
        "dc_fuse_a": ["fuse_pick_a", "dc_fuse_a"],
        "dc_sq": ["dc_sq"],
        "ac_sq": ["ac_sq"],
        "mppt": ["mppt_count", "n_mppt"],
        "receiving": ["receiving", "receiving_mode", "supply_mode"],
        "install_type": ["install_type", "mount_type"],
        "tray_type": ["tray_type"],
        "skip_inverter_outline": ["skip_inverter_outline", "skip_outline"],
    })
    # ── 미인식 표기 LLM 해석 (기본 꺼짐: --llm vertex 로 켬)
    llm_max_texts: int = 200        # 실행당 LLM 에 보낼 서로 다른 문자 수 상한
    llm_batch_size: int = 40        # 호출 한 번에 묶는 문자 수
    llm_max_calls: int = 10         # 실행당 호출 수 상한
    llm_max_chars: int = 200000     # 실행당 프롬프트 총 글자 수 상한
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
            if k in ("i2_factor", "meta_keys"):
                merged = dict(getattr(s, k))
                merged.update(v)
                v = merged
            setattr(s, k, v)
        if s.supply_type not in ("A", "B"):
            raise ValueError("supply_type 은 'A' 또는 'B' 이어야 합니다")
        return s

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
