from __future__ import annotations

from conftest import ids

from dxfcheck.config import Settings


# ── 샘플 도면 ───────────────────────────────────────────────────────────
def test_good_sample_passes(good_report):
    assert good_report.verdict == "적합", [f.title for f in good_report.findings]
    assert [c.result for c in good_report.circuits] == ["적합", "적합", "적합"]
    assert good_report.overview["축척"] == "1/100"


def test_bad_sample_expected_errors(bad_report):
    errors = set(ids(bad_report, "error"))
    assert {"KEC-212.4.1", "KEC-212.3", "KEC-231.3.1", "KEC-234.5", "KEC-232.3.9",
            "KEC-140", "KEC-142.3.1", "KEC-121.2", "DOC-001"} <= errors
    warnings = set(ids(bad_report, "warning"))
    assert {"CAD-003", "CAD-009", "CAD-013", "CAD-014", "KEC-211.2.4", "KEC-203"} <= warnings
    assert bad_report.verdict == "부적합"


# ── 개별 규칙 ───────────────────────────────────────────────────────────
def test_overload_same_row_is_error(make_dxf):
    r = make_dxf([("MCCB 3P 100AF 75AT", 0, 0), ("F-CV 4C 6SQ", 30, 0)])
    assert "KEC-212.4.1" in ids(r, "error")
    assert r.circuits[0].iz_a == 52


def test_overload_ok(make_dxf):
    r = make_dxf([("MCCB 3P 100AF 75AT", 0, 0), ("F-CV 4C 25SQ", 30, 0)])
    assert r.circuits[0].result == "적합"


def test_overload_nearby_is_warning(make_dxf):
    r = make_dxf([("MCCB 3P 100AF 75AT", 0, 0), ("F-CV 4C 6SQ", 0, -20)])
    assert r.circuits[0].basis == "근접"
    assert "KEC-212.4.1" in ids(r, "warning")


def test_parallel_runs_raise_iz(make_dxf):
    r = make_dxf([("ACB 4P 800AF 630AT 50kA", 0, 0), ("2(CV 1C 240SQ×4)", 40, 0)])
    assert r.circuits[0].iz_a == 1000  # 500A × 2조
    assert r.circuits[0].result == "적합"


def test_derating_config(make_dxf):
    s = Settings()
    s.derating = 0.6
    r = make_dxf([("MCCB 3P 100AF 75AT", 0, 0), ("F-CV 4C 25SQ", 30, 0)], settings=s)
    assert "KEC-212.4.1" in ids(r, "error")  # 119 × 0.6 = 71.4 < 75
    assert r.circuits[0].iz_a == round(119 * 0.6, 1)


def test_fuse_i2(make_dxf):
    # 퓨즈 1.6×In: In 50 ≤ Iz 52 이지만 I2 80 > 1.45×52=75.4
    r = make_dxf([("FUSE 50A", 0, 0), ("F-CV 4C 6SQ", 30, 0)])
    f = [x for x in r.findings if x.rule_id == "KEC-212.4.1"][0]
    assert "I2" in f.message and "In 50A > Iz" not in f.message


def test_control_cable_min_size(make_dxf):
    r = make_dxf([("CVV 10C 1.5SQ 제어", 0, 0), ("CVV 4C 0.5SQ", 0, -20)])
    msgs = [f.message for f in r.findings if f.rule_id == "KEC-231.3.1"]
    assert len(msgs) == 1 and "0.5" in msgs[0]


def test_protective_conductor_table(make_dxf):
    r = make_dxf([("MCCB 3P 225AF 200AT 35kA", 0, 0), ("F-CV 4C 95SQ + E 25SQ", 40, 0)])
    assert "KEC-142.3.2" in ids(r, "warning")  # 95/2 = 47.5 필요


def test_separate_pe(make_dxf):
    r = make_dxf([("F-GV 2SQ", 0, 0)])
    assert "KEC-142.3.2" in ids(r, "error")


def test_grounding_lps(make_dxf):
    r = make_dxf([("피뢰 접지도체 F-GV 10SQ", 0, 0)])
    assert "KEC-142.3.1" in ids(r, "error")


def test_voltage_drop_lighting(make_dxf):
    # 1P2W: e = 35.6×60×15/(1000×2.5) = 12.8V → 5.8% > 조명 3%
    r = make_dxf([("MCCB 2P 30AF 20AT", 0, 0), ("HFIX 2.5SQ X 2 L=60m IB=15A 조명", 30, 0)])
    assert "KEC-232.3.9" in ids(r, "error")


def test_voltage_drop_supply_b(make_dxf):
    s = Settings()
    s.supply_type = "B"
    r = make_dxf([("MCCB 2P 30AF 20AT", 0, 0), ("HFIX 2.5SQ X 2 L=60m IB=15A 조명", 30, 0)], settings=s)
    assert "KEC-232.3.9" not in ids(r)  # 6% 한도


def test_outlet_needs_rcd(make_dxf):
    r = make_dxf([("MCCB 2P 30AF 20AT", 0, 0), ("HFIX 2.5SQ X 3", 30, 0), ("전열 콘센트", 60, 0)])
    assert "KEC-211.2.4" in ids(r, "warning")
    r = make_dxf([("ELB 2P 30AF 20AT 30mA", 0, 0), ("HFIX 2.5SQ X 3", 30, 0), ("전열 콘센트", 60, 0)])
    assert "KEC-211.2.4" not in ids(r)


def test_bath_15ma_ok(make_dxf):
    r = make_dxf([("ELB 2P 30AF 20AT 15mA", 0, 0), ("HFIX 2.5SQ X 3", 30, 0), ("욕실 콘센트", 60, 0)])
    assert "KEC-234.5" not in ids(r)


def test_deprecated_and_colors(make_dxf):
    r = make_dxf([("특별제3종접지", 0, 0), ("L1 갈색 L2 흑색 L3 회색 N 청색 PE 녹색-노란색", 0, -10)])
    assert ids(r).count("KEC-140") == 1
    assert "KEC-121.2" not in ids(r)


def test_earthing_declared(make_dxf):
    r = make_dxf([("MCCB 3P 100AF 75AT", 0, 0), ("F-CV 4C 25SQ", 30, 0), ("TN-S", 0, 50)])
    assert "KEC-203" not in ids(r)


def test_conduit_fill(make_dxf):
    # HFIX 16SQ×4 (외경 7.8) in 22C: 191㎟/380㎟ = 50% > 48%
    r = make_dxf([("HFIX 16SQ X 4 (ST 22C)", 0, 0)])
    assert "KEC-232.12" in ids(r, "warning")
    r = make_dxf([("HFIX 16SQ X 4 (ST 36C)", 0, 0)])
    assert "KEC-232.12" not in ids(r)


def test_non_electrical_drawing(make_dxf):
    r = make_dxf([("평면도", 0, 0)])
    assert "KEC-000" in ids(r, "info")


def test_text_height_with_scale(make_dxf):
    r = make_dxf([("축척 1/100", 0, 0), ("작은 글씨", 0, -500)], height=100)
    assert "CAD-015" in ids(r, "warning")  # 100mm/100 = 1mm
