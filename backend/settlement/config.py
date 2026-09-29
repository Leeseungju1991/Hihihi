"""규칙 엔진 임계값. 운영 중 조정 가능하도록 한 곳에 모은다 (env 로 override)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import Decimal


def _dec(name: str, default: str) -> Decimal:
    return Decimal(os.environ.get(name, default))


@dataclass(frozen=True)
class RuleConfig:
    # 3단계: 분개 ÷ 검침량 과 확정 단가의 허용 편차 (원/kWh)
    smp_tolerance: Decimal = Decimal("0.5")
    # 2단계: 분개 ↔ 세금계산서 공급가액 허용 차이 (원) — 원 단위 절사 오차
    amount_tolerance: Decimal = Decimal("10")
    # 4단계: 일 발전시간 상한 퍼센타일
    hours_percentile: Decimal = Decimal("99")
    # 모집단이 너무 작을 때의 하드 상한 (시간/일). 태양광 기준 보수적 값.
    hours_hard_cap: Decimal = Decimal("7.0")
    hours_min_population: int = 20
    # 우선순위 (차이 금액 절대값, 원)
    priority_high: Decimal = Decimal("1000000")
    priority_medium: Decimal = Decimal("100000")

    @classmethod
    def from_env(cls) -> "RuleConfig":
        return cls(
            smp_tolerance=_dec("AX_SMP_TOLERANCE", "0.5"),
            amount_tolerance=_dec("AX_AMOUNT_TOLERANCE", "10"),
            hours_percentile=_dec("AX_HOURS_PERCENTILE", "99"),
            hours_hard_cap=_dec("AX_HOURS_HARD_CAP", "7.0"),
            hours_min_population=int(os.environ.get("AX_HOURS_MIN_POPULATION", "20")),
            priority_high=_dec("AX_PRIORITY_HIGH", "1000000"),
            priority_medium=_dec("AX_PRIORITY_MEDIUM", "100000"),
        )
