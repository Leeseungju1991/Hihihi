"""미인식 표기 LLM 해석 — 가짜 complete 로 검증(네트워크 없음)."""
from __future__ import annotations

import json
import re

import ezdxf

from dxfcheck.analyzer import analyze_dxf, analyze_paths
from dxfcheck.config import Settings
from dxfcheck.drawing import load
from dxfcheck.electrical import parse_all
from dxfcheck.llm import LLMSession, find_candidates, guard
from dxfcheck.samples import build_pv_sheet

BRK = "배선용차단기 3극 100AF 75암페어"
CAB = "케이블 CV 4심 6스퀘어"
ANSWERS = {
    BRK: [{"kind": "breaker", "poles": 3, "af": 100, "at": 75}],
    CAB: [{"kind": "cable", "type": "CV", "cores": 4, "size_sq": 6}],
}


class FakeLLM:
    """프롬프트의 'tN: "원문"' 줄을 읽어 ANSWERS 로 답한다."""

    def __init__(self, answers, fail=False):
        self.answers, self.fail, self.calls, self.prompts = answers, fail, 0, []

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        self.prompts.append(prompt)
        if self.fail:
            raise RuntimeError("network down")
        items = []
        for tid, raw in re.findall(r"^(t\d+): (\".*\")$", prompt, re.M):
            for it in self.answers.get(json.loads(raw), [{"kind": "none"}]):
                items.append(dict(it, id=tid))
        return "```json\n" + json.dumps({"items": items}, ensure_ascii=False) + "\n```"


def _dxf(tmp_path, texts, name="t.dxf"):
    doc = ezdxf.new("R2013")
    doc.header["$INSUNITS"] = 4
    msp = doc.modelspace()
    for t, x, y in texts:
        msp.add_text(t, dxfattribs={"height": 2.5}).set_placement((x, y))
    p = tmp_path / name
    doc.saveas(p)
    return p


def _session(fake, tmp_path=None, **kw):
    s = Settings()
    for k, v in kw.items():
        setattr(s, k, v)
    return LLMSession(fake, s, tmp_path / "cache.json" if tmp_path else None, "fake")


def test_candidates_only_unparsed(tmp_path):
    p = _dxf(tmp_path, [(BRK, 0, 0), (CAB, 30, 0), ("MCCB 3P 100AF 75AT", 0, -10), ("F-CV 4C 6SQ", 30, -10),
                        ("평면도", 0, -20), ("15직렬 X 6병렬", 0, -30)])
    d = load(p, Settings())
    anns = parse_all(d)
    texts = {c.item.text: c.reasons for c in find_candidates(d, anns)}
    assert texts == {BRK: ["breaker"], CAB: ["cable"]}   # 규칙이 읽은 표기는 보내지 않는다


def test_llm_values_judged_by_formula_as_warning(tmp_path):
    p = _dxf(tmp_path, [(BRK, 0, 0), (CAB, 30, 0)])
    fake = FakeLLM(ANSWERS)
    fr = analyze_dxf(p, "t.dxf", Settings(), llm=_session(fake))
    assert fake.calls == 1
    row = fr.circuits[0]
    assert (row.in_a, row.iz_a, row.result) == (75, 52, "주의")       # In 75 > Iz 52 (공식 판정)
    assert "LLM" in row.basis
    f = [x for x in fr.findings if x.rule_id == "KEC-212.4.1"][0]
    assert f.severity.value == "warning" and "(LLM 해석)" in f.title   # 부적합 → 주의로 낮춤
    assert any(x.rule_id == "LLM-001" for x in fr.findings)


def test_prompt_contains_only_candidates(tmp_path):
    p = _dxf(tmp_path, [(BRK, 0, 0), (CAB, 30, 0), ("MCCB 3P 100AF 75AT 비밀메모", 0, -50)])
    fake = FakeLLM(ANSWERS)
    analyze_dxf(p, "t.dxf", Settings(), llm=_session(fake))
    assert "비밀메모" not in fake.prompts[0] and BRK in fake.prompts[0]


def test_guard_rejects_numbers_not_in_text():
    assert guard({"kind": "cable", "size_sq": 10}, "케이블 CV 4심 6스퀘어")[0] is None
    assert guard({"kind": "cable", "size_sq": 6, "type": "MADEUP"}, "케이블 4심 6스퀘어")[1].type is None
    assert guard({"kind": "fact", "name": "rm_rf", "value": 6}, "6")[0] is None
    assert guard({"kind": "breaker", "at": True}, "75A")[0] is None
    assert guard({"kind": "breaker"}, "차단기")[0] is None


def test_rejected_value_not_used(tmp_path):
    p = _dxf(tmp_path, [(BRK, 0, 0), (CAB, 30, 0)])
    bad = {BRK: ANSWERS[BRK], CAB: [{"kind": "cable", "size_sq": 2.5}]}   # 원문에 없는 2.5
    fr = analyze_dxf(p, "t.dxf", Settings(), llm=_session(FakeLLM(bad)))
    assert fr.circuits == []
    llm = [x for x in fr.findings if x.rule_id == "LLM-001"][0]
    assert "거부 1" in llm.message


def test_cache_avoids_second_call(tmp_path):
    p = _dxf(tmp_path, [(BRK, 0, 0), (CAB, 30, 0)])
    f1 = FakeLLM(ANSWERS)
    s1 = _session(f1, tmp_path)
    analyze_paths([p], llm=s1)
    assert f1.calls == 1 and (tmp_path / "cache.json").exists()
    f2 = FakeLLM(ANSWERS)
    r = analyze_paths([p], llm=_session(f2, tmp_path))
    assert f2.calls == 0
    assert r.files[0].circuits[0].result == "주의"


def test_budget_and_failure_fall_back_to_rules(tmp_path):
    p = _dxf(tmp_path, [(BRK, 0, 0), (CAB, 30, 0), ("MCCB 3P 100AF 75AT", 0, -10), ("F-CV 4C 6SQ", 30, -10)])
    f0 = FakeLLM(ANSWERS)
    fr = analyze_dxf(p, "t.dxf", Settings(), llm=_session(f0, llm_max_calls=0))
    assert f0.calls == 0 and any(x.rule_id == "LLM-002" for x in fr.findings)
    fr = analyze_dxf(p, "t.dxf", Settings(), llm=_session(FakeLLM(ANSWERS, fail=True)))
    assert "KEC-212.4.1" in [x.rule_id for x in fr.findings if x.severity.value == "error"]   # 규칙 판정은 그대로
    assert "network down" in " ".join(x.evidence[0] for x in fr.findings if x.rule_id == "LLM-001")


def test_llm_off_reports_unrecognized(tmp_path):
    p = _dxf(tmp_path, [(BRK, 0, 0), (CAB, 30, 0)])
    fr = analyze_dxf(p, "t.dxf", Settings())
    f = [x for x in fr.findings if x.rule_id == "LLM-000"][0]
    assert "2건" in f.message and BRK in f.evidence


def test_set_fact_from_llm_is_warning(tmp_path):
    build_pv_sheet(tmp_path / "E-04.dxf", "E-04")                        # 15직렬 X 6병렬 (규칙)
    p = _dxf(tmp_path, [("모듈결선도", 0, 0), ("직렬 수 16 / 병렬 수 6", 0, -10)], "E-08.dxf")
    assert p.exists()
    ans = {"직렬 수 16 / 병렬 수 6": [{"kind": "fact", "name": "series", "value": 16},
                                   {"kind": "fact", "name": "parallel", "value": 6}]}
    r = analyze_paths([tmp_path], llm=_session(FakeLLM(ans)))
    f = [x for x in r.packages[0].findings if x.rule_id == "SET-E04-1"]
    assert f and f[0].severity.value == "warning" and "LLM" in f[0].title


def test_no_candidates_for_model_codes_and_titles(tmp_path):
    p = _dxf(tmp_path, [("케이블트레이 상세도(1)", 0, 0), ("접지 클램프 SUS304", 0, -10),
                        ("모듈 상세도 HE-550M", 0, -20), ("외함 제3종 접지", 0, -30)])
    d = load(p, Settings())
    assert find_candidates(d, parse_all(d)) == []     # 비용 낭비 방지: 수량 아닌 숫자는 보내지 않는다
