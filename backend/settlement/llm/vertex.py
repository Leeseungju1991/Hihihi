"""Vertex AI 연결부 (회사 GCP). 로컬에서는 import 되지 않는다.

회사 적용 시: requirements 에 google-cloud-aiplatform 추가, AX_LLM=vertex 설정.
사용 모델·리전은 회사 정책에 맞춰 env 로 지정한다.
"""
from __future__ import annotations

import os
from typing import Callable


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
