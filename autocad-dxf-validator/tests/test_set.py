"""도면 세트(E-01~E-21) 검증과 학습 프로파일."""
from __future__ import annotations

import json
import zipfile

import ezdxf
import pytest

from dxfcheck.analyzer import analyze_paths, learn_paths
from dxfcheck.cli import main
from dxfcheck.config import Settings
from dxfcheck.drawing import load
from dxfcheck.drawingset import detect_number
from dxfcheck.profile import Profile
from dxfcheck.samples import GOOD_META, build_pv_set, build_pv_sheet


@pytest.fixture(scope="session")
def pv_dirs(tmp_path_factory):
    root = tmp_path_factory.mktemp("pv")
    return build_pv_set(root / "good"), build_pv_set(root / "bad", bad=True)


@pytest.fixture(scope="session")
def good_set(pv_dirs):
    return analyze_paths([pv_dirs[0]])


@pytest.fixture(scope="session")
def bad_set(pv_dirs):
    return analyze_paths([pv_dirs[1]])


def _ids(pkg, sev=None):
    return [f.rule_id for f in pkg.findings if sev is None or f.severity.value == sev]


def test_good_set_clean(good_set):
    pkg = good_set.packages[0]
    assert len(pkg.sheets) == 22
    assert _ids(pkg) == [], [f.message for f in pkg.findings]
    assert good_set.verdict == "적합"
    assert pkg.metadata["capacity_kw"] == 99.0   # 이진 XRECORD(zlib JSON) 읽기


def test_bad_set_errors(bad_set):
    pkg = bad_set.packages[0]
    errors = set(_ids(pkg, "error"))
    assert {"SET-E01-1", "SET-E01-3", "SET-E02-3", "SET-E04-3", "SET-E05-1", "SET-E11-1", "SET-E21-1"} <= errors
    warnings = set(_ids(pkg, "warning"))
    assert {"SET-E01-2", "SET-E03-2", "SET-E06-P", "SET-E15-1", "SET-P91"} <= warnings
    assert bad_set.verdict == "부적합"


def test_metadata_overrides_majority(tmp_path):
    # 모든 도면이 99kW 라도 설계 메타데이터가 98kW 면 전부 불일치
    meta = json.loads(json.dumps(GOOD_META))
    meta["design"]["as_designed_kw"] = 98.0
    for no in ("E-01", "E-02"):
        build_pv_sheet(tmp_path / ("%s.dxf" % no), no, meta=meta)
    pkg = analyze_paths([tmp_path]).packages[0]
    msgs = [f.message for f in pkg.findings if f.rule_id == "SET-E01-3"]
    assert sum("설계값 98" in m for m in msgs) == 2
    assert any("180장 × 550W = 99kW" in m for m in msgs)   # 메타데이터 자체도 모듈 수×출력과 어긋남


def test_target_capacity_hint(tmp_path):
    meta = json.loads(json.dumps(GOOD_META))
    del meta["design"]["as_designed_kw"]
    build_pv_sheet(tmp_path / "E-04.dxf", "E-04", bad=True, meta=meta)   # 100kW (= p_pv_kw) 표기
    pkg = analyze_paths([tmp_path]).packages[0]
    f = [x for x in pkg.findings if x.title.startswith("설계 용량")]
    assert f and "목표 용량" in f[0].message


def test_number_detection_from_titleblock(tmp_path):
    p = build_pv_sheet(tmp_path / "anything.dxf", "E-09")
    no, sub, src = detect_number("anything.dxf", load(p, Settings()))
    assert (no, src) == ("E-09", "표제란")


def test_standard_layers_setting(tmp_path):
    build_pv_sheet(tmp_path / "E-04.dxf", "E-04")
    s = Settings()
    s.standard_layers = ["TITLE"]
    pkg = analyze_paths([tmp_path], s).packages[0]
    f = [x for x in pkg.findings if x.rule_id == "SET-E04-4"]
    assert f and f[0].evidence == ["E-TEXT"]


def test_single_drawing_has_no_package(tmp_path):
    doc = ezdxf.new()
    doc.modelspace().add_text("평면도")
    doc.saveas(tmp_path / "plan.dxf")
    assert analyze_paths([tmp_path / "plan.dxf"]).packages == []


# ── 학습 ────────────────────────────────────────────────────────────────
def test_learn_and_compare(pv_dirs, tmp_path):
    good, bad = pv_dirs
    prof, log = learn_paths([good])
    assert prof.sets == 1 and prof.sheets["E-11"].n == 2
    path = tmp_path / "p.json"
    prof.save(path)
    prof = Profile.load(path)
    r_good = analyze_paths([good], profile=prof)
    assert not [f for fr in r_good.files for f in fr.findings if f.rule_id.startswith("PRF")]
    r_bad = analyze_paths([bad], profile=prof)
    prf = {f.rule_id for fr in r_bad.files for f in fr.findings if f.rule_id.startswith("PRF")}
    assert "PRF-005" in prf
    assert any(f.rule_id == "PRF-010" for f in r_bad.packages[0].findings)


def test_profile_accumulates_and_escalates(pv_dirs, tmp_path):
    good, _ = pv_dirs
    prof, _ = learn_paths([good, good, good])
    assert prof.sets == 3
    # 학습에 없던 레이어 → 세트 2개 이상 학습 시 '주의'
    p = build_pv_sheet(tmp_path / "E-04.dxf", "E-04")
    doc = ezdxf.readfile(p)
    doc.layers.add("TEMP-XX")
    doc.modelspace().add_line((0, 0), (1, 1), dxfattribs={"layer": "TEMP-XX"})
    doc.saveas(p)
    r = analyze_paths([tmp_path], profile=prof)
    f = [x for fr in r.files for x in fr.findings if x.rule_id == "PRF-001"]
    assert f and f[0].severity.value == "warning" and "TEMP-XX" in f[0].evidence


def test_cli_learn_then_check(pv_dirs, tmp_path):
    good, bad = pv_dirs
    z = tmp_path / "good.zip"
    with zipfile.ZipFile(z, "w") as zf:
        for f in good.glob("*.dxf"):
            zf.write(f, f.name)
    prof = tmp_path / "profiles" / "pv.json"
    assert main(["learn", str(z), "--profile", str(prof)]) == 0
    assert main(["learn", str(z), "--profile", str(prof)]) == 0     # 누적
    assert json.loads(prof.read_text(encoding="utf-8"))["sets"] == 2
    out = tmp_path / "r"
    assert main([str(bad), "--profile", str(prof), "-f", "md", "-o", str(out), "--fail-on", "error"]) == 1
    md = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "도면 세트 정합성" in md and "도면 간 설계 수치 대조" in md and "학습 기준" in md
    assert main([str(bad), "--profile", str(tmp_path / "missing.json")]) == 2
