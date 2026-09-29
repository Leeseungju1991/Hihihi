import json

from settlement.engine.reconcile import reconcile
from settlement.fixtures import demo_bundle, demo_exceptions
from settlement.llm.explainer import LlmExplainer, RuleBasedExplainer, build_prompt


def _result(pid):
    return {r.plant_id: r for r in reconcile(demo_bundle(), demo_exceptions())}[pid]


def test_prompt_contains_only_rule_outputs():
    p = build_prompt(_result("P012"))
    assert "METER_SHORTAGE" in p and "1,307,425원" in p
    assert "판정을 바꾸거나" in p


def test_guard_accepts_grounded_answer():
    r = _result("P012")
    fake = json.dumps(
        {"cause": "송장 검침량 7,000kWh 가 분개 1,307,425원 기준보다 부족", "recommended_action": "누적값 확인", "evidence_keys": ["invoice_kwh", "journal_amount"]},
        ensure_ascii=False,
    )
    exp = LlmExplainer(lambda _: fake).explain(r)
    assert exp.source == "LLM"
    assert [e.key for e in exp.evidence] == ["invoice_kwh", "journal_amount"]


def test_guard_rejects_hallucinated_number():
    r = _result("P012")
    fake = json.dumps({"cause": "검침량 9,999kWh 부족", "recommended_action": "확인", "evidence_keys": []}, ensure_ascii=False)
    exp = LlmExplainer(lambda _: fake).explain(r)
    assert exp.source == "RULE" and "9999" in exp.rejected_reason


def test_guard_rejects_unknown_evidence_key():
    r = _result("P012")
    fake = json.dumps({"cause": "부족", "recommended_action": "확인", "evidence_keys": ["made_up"]}, ensure_ascii=False)
    exp = LlmExplainer(lambda _: fake).explain(r)
    assert exp.source == "RULE" and "made_up" in exp.rejected_reason


def test_model_failure_falls_back():
    def boom(_):
        raise RuntimeError("quota")

    exp = LlmExplainer(boom).explain(_result("P009"))
    assert exp.source == "RULE" and exp.cause


def test_rule_explainer_for_error():
    exp = RuleBasedExplainer().explain(_result("P011"))
    assert "원천" in exp.cause


def test_report_summary_guard():
    from settlement.llm.explainer import guard_summary, rule_summary

    facts = {"month": "2026-08", "total": "12", "PASS": "7", "AUTOMATABLE": "0", "REVIEW": "4", "HOLD": "0", "ERROR": "1",
             "applied": "4", "estimated": "0", "recheck_failed": "1", "approval": "미확정"}
    assert "12개소" in rule_summary(facts)
    ok = guard_summary('{"summary": "2026-08 정산 12개소 중 7개소 통과, 확인 대상 4건"}', facts)
    assert ok.startswith("2026-08")
    exp = LlmExplainer(lambda _: '{"summary": "통과율 58%"}')
    text, source = exp.summarize(facts)
    assert source == "RULE"  # 58 은 집계에 없는 숫자 → 폐기
