"""사용자 식별 — 회사에서는 user-py 로 교체하는 지점 (INTEGRATION.md §3).

기본 동작:
1) IAP 가 붙인 X-Goog-Authenticated-User-Email ("accounts.google.com:user@corp") 를 사용자로 사용
2) AX_IAP_AUDIENCE 가 설정되면 X-Goog-IAP-JWT-Assertion 서명까지 검증 (google-auth 필요)
3) 로컬 개발: AX_DEV_USER 가 있으면 헤더 없이 그 사용자로 동작
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from fastapi import Header, HTTPException


@dataclass(frozen=True)
class User:
    email: str
    is_approver: bool


def _approvers() -> set:
    return {e.strip().lower() for e in os.environ.get("AX_APPROVERS", "").split(",") if e.strip()}


def _verify_iap_jwt(assertion: Optional[str]) -> Optional[str]:  # pragma: no cover - 외부 연동
    audience = os.environ.get("AX_IAP_AUDIENCE")
    if not audience:
        return None
    if not assertion:
        raise HTTPException(status_code=401, detail="IAP JWT 없음")
    from google.auth.transport import requests as g_requests  # type: ignore
    from google.oauth2 import id_token  # type: ignore

    claims = id_token.verify_token(
        assertion,
        g_requests.Request(),
        audience=audience,
        certs_url="https://www.gstatic.com/iap/verify/public_key",
    )
    return claims.get("email")


def current_user(
    x_goog_authenticated_user_email: Optional[str] = Header(default=None),
    x_goog_iap_jwt_assertion: Optional[str] = Header(default=None),
) -> User:
    email = _verify_iap_jwt(x_goog_iap_jwt_assertion)
    if email is None and x_goog_authenticated_user_email:
        email = x_goog_authenticated_user_email.split(":", 1)[-1]
    if email is None:
        email = os.environ.get("AX_DEV_USER")
    if not email:
        raise HTTPException(status_code=401, detail="인증 정보 없음")
    approvers = _approvers()
    return User(email=email, is_approver=(not approvers) or email.lower() in approvers)
