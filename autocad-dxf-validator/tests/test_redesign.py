"""재설계 루프: 규칙 수정 → 재검증 · 회귀 되돌림 · 피드백 학습 · LLM 수정안 · ZIP."""
from __future__ import annotations

import json
import zipfile

import ezdxf
import pytest

from dxfcheck.redesign import FeedbackStore, finding_pattern, redesign
from dxfcheck.redesign.llm_fix import guard as fix_guard
from dxfcheck.samples import build_bad, build_pv_set


@pytest.fixture
def bad_panel(tmp_path):
    d = tmp_path / "in"
    d.mkdir()
    build_bad(d / "panel.dxf")
    return d


def _texts(p):
    return [e.dxf.text for e in ezdxf.readfile(p).modelspace().query("TEXT")]


def test_rule_fixes_and_zip(bad_panel, tmp_path):
    out = tmp_path / "out.zip"
    r = redesign(bad_panel, out_zip=out, work_dir=tmp_path / "wd")
    e0, e1 = r.rounds[0].errors_before, r.rounds[-1].errors_after
    assert e1 < e0 and r.status == "개선"
    after = {c.after for c in r.changes if c.ok and not c.reverted}
    assert {"F-CV 4C 16SQ", "HFIX 2.5SQ X 2", "MCCB 3P 60AF 60AT", "ELB 2P 30AF 20AT 15mA",
            "외함 보호접지 시행", "접지선 GV 6SQ"} <= after
    assert not any(x.new_errors for x in r.rounds)
    names = zipfile.ZipFile(out).namelist()
    assert "design/panel.dxf" in names and "reports/after.md" in names and "reports/redesign.md" in names
    zipfile.ZipFile(out).extract("design/panel.dxf", tmp_path / "x")
    assert "F-CV 4C 16SQ" in _texts(tmp_path / "x" / "design" / "panel.dxf")
    assert ezdxf.readfile(tmp_path / "x" / "design" / "panel.dxf").header["$INSUNITS"] == 4
    rj = json.loads(zipfile.ZipFile(out).read("reports/redesign.json"))
    assert rj["status"] == "개선" and rj["before"]["counts"]["error"] == e0


def test_set_fixes_and_regenerator(tmp_path):
    src = build_pv_set(tmp_path / "pv", bad=True)
    calls = []

    def regen(reqs, working):
        calls.append([r["drawing"] for r in reqs])
        return []

    r = redesign(src, work_dir=tmp_path / "wd", regenerator=regen)
    rules = {c.rule_id for c in r.changes if c.ok}
    assert {"SET-E01-3", "SET-E04-3", "SET-E05-1", "SET-P91", "SET-E01-2"} <= rules
    assert calls and {"E-07", "E-04", "E-11", "E-21"} <= set(calls[0])
    items = {i["no"]: i["status"] for i in r.to_dict()["after"]["items21"]}
    assert len(items) == 21 and items["E-05"] != "부적합"


def test_manual_regenerate_without_hook(tmp_path):
    r = redesign(build_pv_set(tmp_path / "pv", bad=True), work_dir=tmp_path / "wd")
    assert any(m.get("regenerate") for m in r.manual)


def test_clean_set_no_changes(tmp_path):
    r = redesign(build_pv_set(tmp_path / "pv"), work_dir=tmp_path / "wd")
    assert r.status == "통과" and not r.changes


def test_feedback_reject_blocks_fix(bad_panel, tmp_path):
    store = FeedbackStore(path=tmp_path / "fb.json")
    first = redesign(bad_panel, work_dir=tmp_path / "w0", max_rounds=1, feedback=FeedbackStore())
    f = next(x for x in first.before.all_findings() if x.rule_id == "KEC-231.3.1")
    store.record(f.rule_id, finding_pattern(f, tmp_path / "w0" / "original"), "reject")
    r = redesign(bad_panel, work_dir=tmp_path / "w1", feedback=store)
    assert not any(c.rule_id == "KEC-231.3.1" for c in r.changes)
    assert any(m["rule_id"] == "KEC-231.3.1" and "피드백" in m["why"] for m in r.manual)
    assert json.loads((tmp_path / "fb.json").read_text(encoding="utf-8"))["entries"]


def test_feedback_correct_is_learned(bad_panel, tmp_path):
    store = FeedbackStore()
    first = redesign(bad_panel, work_dir=tmp_path / "w0", max_rounds=1, feedback=FeedbackStore())
    f = next(x for x in first.before.all_findings() if x.rule_id == "KEC-140")
    store.record(f.rule_id, finding_pattern(f, tmp_path / "w0" / "original"), "correct", "외함 보호접지(PE) 시설")
    r = redesign(bad_panel, work_dir=tmp_path / "w1", feedback=store)
    c = next(c for c in r.changes if c.rule_id == "KEC-140")
    assert c.confidence == "memory" and c.after == "외함 보호접지(PE) 시설"


def test_auto_learning_counts(bad_panel, tmp_path):
    store = FeedbackStore()
    redesign(bad_panel, work_dir=tmp_path / "wd", feedback=store)
    oks = [e for e in store.entries.values() if e.ok]
    assert oks and store.examples("KEC-231.3.1")


class FakeFix:
    def __init__(self, new_text):
        self.new_text, self.calls = new_text, 0

    def __call__(self, prompt):
        self.calls += 1
        return json.dumps({"new_text": self.new_text, "reason": "test"}, ensure_ascii=False)


def test_llm_fix_success(bad_panel, tmp_path):
    # KEC-211.2.4(옥외 콘센트 누전차단기 없음)은 규칙 수정안이 없어 LLM 에 묻는다
    fake = FakeFix("ELB 2P 30AF 20AT 30mA")
    r = redesign(bad_panel, work_dir=tmp_path / "wd", fix_complete=fake)
    c = [c for c in r.changes if c.rule_id == "KEC-211.2.4"]
    assert c and c[0].confidence == "llm" and c[0].ok and not c[0].reverted
    assert not any(f.rule_id == "KEC-211.2.4" for f in r.after.all_findings())


def test_llm_fix_regression_reverted(bad_panel, tmp_path):
    fake = FakeFix("MCCB 2P 30AF 50AT")      # AT > AF → 새 부적합 → 되돌림
    store = FeedbackStore()
    r = redesign(bad_panel, work_dir=tmp_path / "wd", fix_complete=fake, feedback=store)
    c = [c for c in r.changes if c.rule_id == "KEC-211.2.4"][0]
    assert c.reverted and any(x.new_errors for x in r.rounds)
    assert "MCCB 2P 30AF 50AT" not in _texts(tmp_path / "wd" / "working" / "panel.dxf")
    assert any(e.rule_id == "KEC-211.2.4" and e.fail for e in store.entries.values())


def test_llm_fix_guard():
    allowed = [2, 30, 20, 15]
    assert fix_guard("ELB 2P 30AF 20AT 30mA", "ELB 2P 30AF 20AT 15mA", allowed) is None
    assert "숫자" in fix_guard("ELB 2P 30AF 20AT 30mA", "ELB 2P 30AF 20AT 17mA", allowed)
    assert fix_guard("ELB 2P 30AF 20AT", "rm -rf / 이것은 전혀 다른 문장입니다", allowed)
    assert fix_guard("ELB 2P 30AF 20AT", "ELB 2P 30AF 20AT", allowed) == "변경 없음"
