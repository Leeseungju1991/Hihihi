"""[미검증 · 회사 연결 예정] Vertex AI(Gemini) 연결 — 기능만 구현, 실제 호출 검증 안 함.

정산 오케스트레이터(backend/settlement/llm/vertex.py)와 같은 방식이다.
  pip install google-cloud-aiplatform
  GOOGLE_CLOUD_PROJECT=<프로젝트>  AX_LLM_MODEL=<모델>  [AX_LLM_LOCATION=asia-northeast3]
  dxfcheck 도면.zip --llm vertex
"""
from __future__ import annotations

import os
from typing import Callable


def model_name() -> str:
    return os.environ.get("AX_LLM_MODEL", "")


def make_vertex_complete() -> Callable[[str], str]:  # pragma: no cover - 외부 연동
    import vertexai  # type: ignore
    from vertexai.generative_models import GenerationConfig, GenerativeModel  # type: ignore

    vertexai.init(
        project=os.environ["GOOGLE_CLOUD_PROJECT"],
        location=os.environ.get("AX_LLM_LOCATION", "asia-northeast3"),
    )
    model = GenerativeModel(os.environ["AX_LLM_MODEL"])
    config = GenerationConfig(temperature=0, response_mime_type="application/json")

    def complete(prompt: str) -> str:
        return model.generate_content(prompt, generation_config=config).text

    return complete
