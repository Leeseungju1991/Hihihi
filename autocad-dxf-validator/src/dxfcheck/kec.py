"""KEC(한국전기설비규정) 기준값.

수치는 KEC(2021 시행본 이후)와 KEC가 인용하는 KS C IEC 60364-5-52 부속서 B 를 옮긴 것이다.
개정판이 나오면 이 파일만 고친다. 규칙 코드(rules/kec_rules.py)는 수치를 직접 갖지 않는다.
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

# ── 허용전류 표 (구리, 주위온도 30℃, 공기 중) ─────────────────────────────
# KS C IEC 60364-5-52 표 B.52.2~B.52.5. 키: (절연체, 공사방법, 부하도체 수)
SIZES = (1.5, 2.5, 4, 6, 10, 16, 25, 35, 50, 70, 95, 120, 150, 185, 240, 300)

_AMPACITY_ROWS: Dict[Tuple[str, str, int], Tuple[float, ...]] = {
    # PVC 70℃
    ("PVC", "A1", 2): (14.5, 19.5, 26, 34, 46, 61, 80, 99, 119, 151, 182, 210, 240, 273, 321, 367),
    ("PVC", "B1", 2): (17.5, 24, 32, 41, 57, 76, 101, 125, 151, 192, 232, 269, 300, 341, 400, 458),
    ("PVC", "C", 2): (19.5, 27, 36, 46, 63, 85, 112, 138, 168, 213, 258, 299, 344, 392, 461, 530),
    ("PVC", "A1", 3): (13.5, 18, 24, 31, 42, 56, 73, 89, 108, 136, 164, 188, 216, 245, 286, 328),
    ("PVC", "B1", 3): (15.5, 21, 28, 36, 50, 68, 89, 110, 134, 171, 207, 239, 262, 296, 346, 394),
    ("PVC", "C", 3): (17.5, 24, 32, 41, 57, 76, 96, 119, 144, 184, 223, 259, 299, 341, 403, 464),
    # XLPE/EPR 90℃
    ("XLPE", "A1", 2): (19, 26, 35, 45, 61, 81, 106, 131, 158, 200, 241, 278, 318, 362, 424, 486),
    ("XLPE", "B1", 2): (23, 31, 42, 54, 75, 100, 133, 164, 198, 253, 306, 354, 393, 449, 528, 603),
    ("XLPE", "C", 2): (24, 33, 45, 58, 80, 107, 138, 171, 209, 269, 328, 382, 441, 506, 599, 693),
    ("XLPE", "A1", 3): (17, 23, 31, 40, 54, 73, 95, 117, 141, 179, 216, 249, 285, 324, 380, 435),
    ("XLPE", "B1", 3): (20, 28, 37, 48, 66, 88, 117, 144, 175, 222, 269, 312, 342, 384, 450, 514),
    ("XLPE", "C", 3): (22, 30, 40, 52, 71, 96, 119, 147, 179, 229, 278, 322, 371, 424, 500, 576),
}
AMPACITY_REF = "KEC 232.5.1 (KS C IEC 60364-5-52 표 B.52.2~B.52.5, 구리·30℃)"


def ampacity(insulation: str, method: str, loaded: int, size: float) -> Optional[float]:
    row = _AMPACITY_ROWS.get((insulation, method, loaded))
    if row is None:
        return None
    for s, a in zip(SIZES, row):
        if abs(s - size) < 1e-6:
            return float(a)
    return None


# ── 전선 종류 ───────────────────────────────────────────────────────────
# 절연체 · 단심 절연전선 여부 · 저압 여부
CABLE_TYPES: Dict[str, Tuple[str, bool, bool]] = {
    "TFR-CV": ("XLPE", False, True),
    "FR-CV": ("XLPE", False, True),
    "F-CV": ("XLPE", False, True),
    "FCV": ("XLPE", False, True),
    "CV": ("XLPE", False, True),
    "HFCO": ("XLPE", False, True),
    "F-FR-8": ("XLPE", False, True),
    "FR-8": ("XLPE", False, True),
    "FR-3": ("PVC", False, True),
    "F-CVV": ("PVC", False, True),
    "CVVS": ("PVC", False, True),
    "CVV": ("PVC", False, True),
    "VCT": ("PVC", False, True),
    "HFIX": ("XLPE", True, True),
    "HIV": ("PVC", True, True),
    "KIV": ("PVC", True, True),
    "IV": ("PVC", True, True),
    "H1Z2Z2-K": ("XLPE", False, True),   # 태양광 DC 전용 (KS C IEC 62930, DC 1.5kV)
    "PV": ("XLPE", False, True),
    "CNCV-W": ("XLPE", False, False),
    "CNCV": ("XLPE", False, False),
    "FR-CNCO-W": ("XLPE", False, False),
}
CONTROL_CABLES = ("CVV", "CVVS", "F-CVV", "VCT", "FR-3")

# ── 최소 단면적 (KEC 231.3.1 저압 옥내배선의 사용전선) ─────────────────────
MIN_SIZE_POWER = 2.5      # 연동선 2.5㎟ 이상
MIN_SIZE_CONTROL = 1.5    # 전광표시장치·제어회로 등 1.5㎟ 이상
MIN_SIZE_CONTROL_MULTICORE = 0.75  # 제어회로 다심케이블·다심캡타이어 0.75㎟ 이상
MIN_SIZE_REF = "KEC 231.3.1"

# ── 보호도체 (KEC 142.3.2) ────────────────────────────────────────────
PE_REF = "KEC 142.3.2 (표 142.3-1)"


def pe_required(phase_size: float) -> float:
    """상도체와 같은 재질일 때 보호도체 최소 단면적."""
    if phase_size <= 16:
        return phase_size
    if phase_size <= 35:
        return 16.0
    return phase_size / 2.0


PE_SEPARATE_MECH = 2.5   # 케이블 일부가 아닌 보호도체: 기계적 보호 있음
PE_SEPARATE_NOMECH = 4.0  # 기계적 보호 없음

# ── 접지도체 (KEC 142.3.1) ────────────────────────────────────────────
GROUND_MIN = 6.0         # 큰 고장전류가 흐르지 않는 경우 구리 6㎟ 이상
GROUND_MIN_LPS = 16.0    # 피뢰시스템이 접속되는 경우 구리 16㎟ 이상
GROUND_REF = "KEC 142.3.1"

# ── 과부하 보호 (KEC 212.4.1) ─────────────────────────────────────────
OVERLOAD_REF = "KEC 212.4.1 (IB ≤ In ≤ IZ, I2 ≤ 1.45 × IZ)"

# ── 전압강하 (KEC 232.3.9 표 232.3-1) ──────────────────────────────────
VDROP_LIMIT = {("A", "lighting"): 3.0, ("A", "other"): 5.0, ("B", "lighting"): 6.0, ("B", "other"): 8.0}
VDROP_REF = "KEC 232.3.9 (표 232.3-1)"


def vdrop_limit(supply: str, use: str, length_m: float) -> float:
    base = VDROP_LIMIT[(supply, use)]
    if length_m > 100:  # 100m 초과분 1m당 0.005% 증가, 증가분 0.5% 이하
        base += min(0.5, (length_m - 100) * 0.005)
    return base


# 전압강하 계수 e = K·L·I / (1000·A)  [V]  (구리, 내선규정 간이식)
VDROP_K = {"1P2W": 35.6, "3P3W": 30.8, "3P4W": 17.8, "1P3W": 17.8}

# ── 누전차단기 (KEC 211.2.4, 234.5) ────────────────────────────────────
RCD_REF = "KEC 211.2.4"
RCD_BATH_REF = "KEC 234.5 (욕실 등: 인체감전보호용 15mA 이하·0.03초 이하)"
RCD_BATH_MAX_MA = 15
RCD_GENERAL_MAX_MA = 30

# ── 전선 식별 (KEC 121.2 표 121.2-1) ──────────────────────────────────
COLOR_REF = "KEC 121.2 (L1 갈색, L2 흑색, L3 회색, N 청색, PE 녹색-노란색)"
CONDUCTOR_COLORS = {
    "L1": ("갈",),
    "L2": ("흑", "검"),
    "L3": ("회",),
    "N": ("청", "파"),
    "PE": ("녹황", "녹색-노란", "녹색-황", "녹-황", "녹/황", "녹색/노란", "녹색노란", "황녹"),
}

# ── 표준 정격 (KS C IEC 60947-2, 국내 상용 정격 포함) ─────────────────────
STD_AT = {
    1, 2, 3, 4, 5, 6, 10, 13, 15, 16, 20, 25, 30, 32, 40, 50, 60, 63, 75, 80, 100, 125, 150, 160,
    175, 200, 225, 250, 300, 350, 400, 500, 600, 630, 700, 800, 1000, 1200, 1250, 1600, 2000,
    2500, 3200, 4000, 5000, 6300,
}
STD_AF = {30, 32, 50, 60, 63, 100, 125, 160, 200, 225, 250, 400, 600, 630, 800, 1000, 1200, 1250,
          1600, 2000, 2500, 3200, 4000, 5000, 6300}
STD_RCD_MA = {6, 10, 15, 30, 100, 200, 300, 500, 1000}

# ── 전선관 (내선규정 전선관 굵기 선정 — 피복 포함 총단면적/관 내단면적) ─────────
CONDUIT_FILL_SAME = 48.0   # 동일 굵기 절연전선
CONDUIT_FILL_MIXED = 32.0  # 굵기가 다른 절연전선
CONDUIT_REF = "내선규정 전선관 굵기 선정 (KEC 232 배선설비 연계)"
# HFIX 450/750V 대략 완성 외경(mm) — 제조사 사양으로 교체 가능
HFIX_OD = {1.5: 3.3, 2.5: 4.0, 4: 4.6, 6: 5.2, 10: 6.7, 16: 7.8, 25: 9.7, 35: 11.0,
           50: 13.0, 70: 15.0, 95: 17.0, 120: 19.0}


# ── 재설계용 역산 ───────────────────────────────────────────────────────
def min_size_for_current(insulation: str, method: str, loaded: int, need_a: float,
                         parallel: int = 1, derating: float = 1.0) -> Optional[float]:
    """허용전류 Iz × 병렬 × 보정 ≥ need_a 를 만족하는 최소 표준 단면적."""
    for s in SIZES:
        a = ampacity(insulation, method, loaded, s)
        if a is not None and a * parallel * derating >= need_a - 1e-9:
            return float(s)
    return None


def next_size(at_least: float) -> Optional[float]:
    for s in SIZES:
        if s >= at_least - 1e-9:
            return float(s)
    return None


def next_frame(at: float) -> Optional[float]:
    for f in sorted(STD_AF):
        if f >= at - 1e-9:
            return float(f)
    return None
