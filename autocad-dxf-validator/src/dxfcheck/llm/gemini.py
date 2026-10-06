"""[미검증 · 회사 연결 예정] Gemini API(키 방식) — 키는 GCP Secret Manager 에서 읽는다.

키 찾는 순서
  1. GEMINI_API_KEY            — Cloud Run 에서 `--set-secrets GEMINI_API_KEY=<secret>:latest` 로 주입(권장, 코드 불필요)
  2. GEMINI_API_KEY_SECRET     — 'projects/<p>/secrets/<s>/versions/latest' 를 Secret Manager 에서 직접 읽음
                                 (pip install google-cloud-secret-manager, 서비스 계정에 secretAccessor 권한)
모델: GEMINI_MODEL (필수, 예: 회사 표준 Gemini 모델명). 키는 URL 이 아니라 x-goog-api-key 헤더로 보낸다(로그 노출 방지).
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Callable, Optional

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent"


def get_api_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    name = os.environ.get("GEMINI_API_KEY_SECRET", "").strip()
    if not name:
        raise RuntimeError("GEMINI_API_KEY 또는 GEMINI_API_KEY_SECRET 이 필요합니다")
    from google.cloud import secretmanager  # type: ignore  # pragma: no cover - 외부 연동

    client = secretmanager.SecretManagerServiceClient()  # pragma: no cover
    return client.access_secret_version(name=name).payload.data.decode("utf-8").strip()  # pragma: no cover


def model_name() -> str:
    return os.environ.get("GEMINI_MODEL", "")


def make_gemini_complete(api_key: Optional[str] = None, model: Optional[str] = None,
                         timeout: float = 60.0, opener=None) -> Callable[[str], str]:
    key = api_key or get_api_key()
    model = model or model_name()
    if not model:
        raise RuntimeError("GEMINI_MODEL 이 필요합니다")
    url = ENDPOINT % model
    open_ = opener or urllib.request.urlopen

    def complete(prompt: str) -> str:
        body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json", "x-goog-api-key": key})
        with open_(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(p.get("text", "") for p in parts)

    return complete
