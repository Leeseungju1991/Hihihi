"""LLM 역할(제한) — 실패 원인 설명·추천 조치 작성만 한다.

- 입력: 규칙 판정 결과(PlantResult)의 태그·메시지·근거값
- 출력: cause / recommended_action / evidence(근거 키 목록)
- 금액·발전량을 결정하거나 보정값을 반영하지 않는다 (출력을 쓰는 코드가 없음).
- 가드: 인용한 근거 키가 입력에 없거나, 설명 문장 속 숫자가 입력 근거값에 없으면 폐기 → 규칙 기반 설명으로 대체.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from ..domain.models import Evidence, IssueTag, PlantResult

ACTIONS = {
    IssueTag.METER_SHORTAGE: "검침 누적값(모니터링) 확인 후 누락분 보정 또는 수기 발행 예외 등록",
    IssueTag.DOUBLE_COUNT: "중복 송장·세금계산서·분개 여부 확인 후 한 건 취소 요청",
    IssueTag.PARTNER_MISMATCH: "양수도·거래처 변경·PPA 지연 예외(기준일, 변경 전·후 조합) 등록",
    IssueTag.HOURS_EXCEEDED: "설비용량·검침값 오입력 여부 확인 (이중계상 가능성 포함)",
    IssueTag.INVALID_TAX_INVOICE: "홈택스 원본으로 무효/수정 세금계산서 상태 확인 후 에러 케이스 등록",
}

CAUSES = {
    IssueTag.METER_SHORTAGE: "송장 검침량이 분개 기준 역산 검침량보다 적음",
    IssueTag.DOUBLE_COUNT: "검침량 또는 증빙이 중복 계상된 것으로 보임",
    IssueTag.PARTNER_MISMATCH: "조합(거래처)별 금액·검침량 귀속이 분개와 다름",
    IssueTag.HOURS_EXCEEDED: "일 평균 발전시간이 통계적 상한을 넘음",
    IssueTag.INVALID_TAX_INVOICE: "무효/음수 세금계산서 처리 상태가 비정상",
}


@dataclass
class Explanation:
    cause: str
    recommended_action: str
    evidence: List[Evidence] = field(default_factory=list)
    source: str = "RULE"  # RULE | LLM
    rejected_reason: str = ""  # LLM 출력이 가드에서 폐기된 사유


class Explainer:
    def explain(self, result: PlantResult) -> Explanation:  # pragma: no cover - interface
        raise NotImplementedError

    def summarize(self, facts: Dict[str, str]) -> Tuple[str, str]:
        """리포트 요약 (text, source). 기본은 결정적 요약."""
        return rule_summary(facts), "RULE"


def rule_summary(facts: Dict[str, str]) -> str:
    parts = [
        "{month} 정산: 대상 {total}개소 중 통과 {PASS}, 자동화 대상 {AUTOMATABLE}, 확인 대상 {REVIEW}, 보류 {HOLD}, 에러 {ERROR}.".format(**facts),
        "자동화 보정 {applied}건(추정 {estimated}건), 재검증 미통과 {recheck_failed}건.".format(**facts),
    ]
    if facts.get("HOLD", "0") != "0":
        parts.append("보류 건은 사유와 함께 별도 표기됨.")
    parts.append("확정 상태: {approval}.".format(**facts))
    return " ".join(parts)


class RuleBasedExplainer(Explainer):
    """결정적 설명. LLM 미연결·가드 실패 시 기본값."""

    def explain(self, result: PlantResult) -> Explanation:
        if result.error:
            return Explanation(
                cause="원천 데이터 오류: " + result.error,
                recommended_action="원천 재수집 후 재검증, 반복되면 에러 케이스 등록",
                evidence=list(result.evidence),
            )
        if not result.tags:
            return Explanation(cause="불일치 없음", recommended_action="-", evidence=list(result.evidence))
        primary = result.tags[0]
        cause = "{} — {}".format(CAUSES[primary], result.summary) if result.summary else CAUSES[primary]
        actions = [ACTIONS[t] for t in result.tags]
        return Explanation(cause=cause, recommended_action=" / ".join(actions), evidence=list(result.evidence))


PROMPT = """당신은 발전매출 정산 대조 결과를 설명하는 보조자입니다.
규칙 엔진이 이미 판정을 끝냈습니다. 당신은 판정을 바꾸거나 새 금액·발전량을 계산하지 않습니다.
아래 근거값만 인용해 실패 원인과 추천 조치를 한국어 한두 문장으로 작성하세요.
숫자를 쓸 때는 근거값에 있는 문자열을 그대로 쓰세요. 근거값에 없는 숫자는 쓰지 마세요.

[발전소] {plant_name} ({plant_id}) / 정산월 {month}
[판정 태그] {tags}
[규칙 메시지]
{messages}
[근거값]
{facts}
[적용된 자동화]
{adjustments}

다음 JSON 한 개만 출력하세요:
{{"cause": "...", "recommended_action": "...", "evidence_keys": ["근거값 key", ...]}}
"""


def build_prompt(result: PlantResult, messages: Optional[List[str]] = None) -> str:
    facts = "\n".join("- {} ({}): {}".format(e.key, e.label, e.value) for e in result.evidence)
    adjs = "\n".join("- " + a.formula for a in result.candidate_adjustments) or "- 없음"
    return PROMPT.format(
        plant_name=result.plant_name,
        plant_id=result.plant_id,
        month=result.month,
        tags=", ".join(t.value for t in result.tags) or "없음",
        messages="\n".join("- " + m for m in (messages or [result.summary])),
        facts=facts or "- 없음",
        adjustments=adjs,
    )


_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> List[str]:
    return [n.replace(",", "") for n in _NUM.findall(text)]


def guard(raw: str, result: PlantResult) -> Explanation:
    """LLM 출력 검증. 실패 시 ValueError."""
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("JSON 없음")
    data = json.loads(m.group(0))
    cause = str(data.get("cause", "")).strip()
    action = str(data.get("recommended_action", "")).strip()
    keys = data.get("evidence_keys") or []
    if not cause or not action:
        raise ValueError("cause/recommended_action 누락")

    by_key: Dict[str, Evidence] = {e.key: e for e in result.evidence}
    unknown = [k for k in keys if k not in by_key]
    if unknown:
        raise ValueError("존재하지 않는 근거 키: {}".format(unknown))

    allowed = set()
    for e in result.evidence:
        allowed.update(_numbers(e.value))
    allowed.update(_numbers(result.month))
    allowed.update(_numbers(result.plant_id))
    allowed.update(_numbers(result.plant_name))
    stray = [n for n in _numbers(cause + " " + action) if n not in allowed]
    if stray:
        raise ValueError("근거값에 없는 숫자 인용: {}".format(stray))

    cited = [by_key[k] for k in keys] or list(result.evidence)
    return Explanation(cause=cause, recommended_action=action, evidence=cited, source="LLM")


SUMMARY_PROMPT = """아래는 발전매출 정산 결과 집계입니다. 담당자에게 보고할 요약을 한국어 3문장 이내로 작성하세요.
집계값에 있는 숫자만 쓰고, 새 숫자를 계산하거나 추정하지 마세요. 판단·권고는 하지 말고 사실만 요약하세요.

[집계]
{facts}

다음 JSON 한 개만 출력하세요: {{"summary": "..."}}
"""


def guard_summary(raw: str, facts: Dict[str, str]) -> str:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        raise ValueError("JSON 없음")
    text = str(json.loads(m.group(0)).get("summary", "")).strip()
    if not text:
        raise ValueError("summary 누락")
    allowed = set()
    for v in facts.values():
        allowed.update(_numbers(str(v)))
    stray = [n for n in _numbers(text) if n not in allowed]
    if stray:
        raise ValueError("집계에 없는 숫자 인용: {}".format(stray))
    return text


class LlmExplainer(Explainer):
    """complete(prompt) -> str 만 주입하면 어떤 모델이든 사용 가능 (Vertex AI Gemini, Claude 등)."""

    def __init__(self, complete: Callable[[str], str], fallback: Optional[Explainer] = None):
        self._complete = complete
        self._fallback = fallback or RuleBasedExplainer()

    def explain(self, result: PlantResult) -> Explanation:
        if not result.tags and not result.error:
            return self._fallback.explain(result)
        try:
            raw = self._complete(build_prompt(result))
            return guard(raw, result)
        except Exception as exc:  # 모델 오류·가드 실패 모두 결정적 설명으로 대체
            fb = self._fallback.explain(result)
            fb.rejected_reason = str(exc)
            return fb

    def summarize(self, facts: Dict[str, str]) -> Tuple[str, str]:
        try:
            prompt = SUMMARY_PROMPT.format(facts="\n".join("- {}: {}".format(k, v) for k, v in facts.items()))
            return guard_summary(self._complete(prompt), facts), "LLM"
        except Exception:
            return rule_summary(facts), "RULE"
