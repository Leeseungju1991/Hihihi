"""FastAPI 앱. 라우터는 얇게 — 로직은 SettlementService 에 있다.

실행: uvicorn settlement.api.app:app --reload   (AX_BACKEND=memory, AX_DEV_USER=dev@local)
"""
from __future__ import annotations

import datetime as dt
import os
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config import RuleConfig
from ..domain.models import (
    Category,
    ErrorCase,
    ExceptionStatus,
    ExceptionType,
    IssueTag,
    SettlementException,
)
from ..domain.validation import REQUIRED_FIELDS, ValidationError
from ..engine.reconcile import TAG_LABELS
from ..llm.explainer import Explainer, LlmExplainer, RuleBasedExplainer
from ..ports import Repositories
from ..report.builder import build_report
from ..workflow.service import (
    ConfirmationRequired,
    MonthLockedError,
    NotFoundError,
    SettlementService,
)
from .auth import User, current_user
from .serialize import dump

CATEGORY_LABELS = {
    Category.PASS: "통과",
    Category.AUTOMATABLE: "자동화 대상",
    Category.REVIEW: "확인 대상",
    Category.HOLD: "보류",
    Category.ERROR: "에러",
}
EXCEPTION_TYPE_LABELS = {
    ExceptionType.TRANSFER: "양수도",
    ExceptionType.MANUAL_ISSUE: "수기 발행",
    ExceptionType.PARTNER_CHANGE: "거래처 변경",
    ExceptionType.PPA_DELAY: "PPA 변경 지연",
    ExceptionType.OTHER: "기타",
}
EXCEPTION_STATUS_LABELS = {
    ExceptionStatus.REGISTERED: "등록",
    ExceptionStatus.ACTIVE: "적용 중",
    ExceptionStatus.CLOSED: "종료",
}


# ─────────── 요청 스키마 (pydantic v1/v2 공용 문법만 사용) ───────────


class ExceptionIn(BaseModel):
    month: str
    plant_id: str
    type: ExceptionType
    base_date: Optional[dt.date] = None
    partner_before: str = ""
    partner_after: str = ""
    manual_kwh: Optional[str] = None  # Decimal 문자열
    note: str = ""


class PlantIdsIn(BaseModel):
    plant_ids: Optional[List[str]] = None


class HoldIn(BaseModel):
    reason: str


class ErrorCaseIn(BaseModel):
    occurred_on: dt.date
    month: str
    plant_id: str
    symptom: str


class FinalizeIn(BaseModel):
    acknowledge: bool = False
    note: str = ""


def _to_exception(body: ExceptionIn, exception_id: str = "") -> SettlementException:
    manual = None
    if body.manual_kwh not in (None, ""):
        try:
            manual = Decimal(str(body.manual_kwh))
        except InvalidOperation:
            raise ValidationError({"manual_kwh": "숫자여야 합니다"})
    return SettlementException(
        exception_id=exception_id,
        month=body.month,
        plant_id=body.plant_id,
        type=body.type,
        base_date=body.base_date,
        partner_before=body.partner_before.strip(),
        partner_after=body.partner_after.strip(),
        manual_kwh=manual,
        note=body.note,
    )


# ─────────── 앱 조립 ───────────


def build_repositories() -> Repositories:
    backend = os.environ.get("AX_BACKEND", "memory")
    if backend == "bigquery":  # pragma: no cover - 회사 환경
        from ..adapters.bigquery import bigquery_repositories

        return bigquery_repositories()
    from ..adapters.memory import memory_repositories
    from ..fixtures import demo_bundle

    bundle = demo_bundle()
    return memory_repositories({bundle.month: bundle})


def build_explainer() -> Explainer:
    if os.environ.get("AX_LLM") == "vertex":  # pragma: no cover - 회사 환경
        from ..llm.vertex import make_vertex_complete

        return LlmExplainer(make_vertex_complete())
    return RuleBasedExplainer()


def create_app(service: Optional[SettlementService] = None, seed_demo: Optional[bool] = None) -> FastAPI:
    if service is None:
        service = SettlementService(build_repositories(), build_explainer(), RuleConfig.from_env())
        if seed_demo is None:
            seed_demo = os.environ.get("AX_BACKEND", "memory") == "memory"
    if seed_demo:
        from ..fixtures import demo_exceptions

        for exc in demo_exceptions():
            service.create_exception(exc, "seed@local")

    app = FastAPI(title="AX 정산 오케스트레이터", version="0.1.0")
    app.state.service = service

    @app.exception_handler(ValidationError)
    async def _validation(_: Request, exc: ValidationError):
        return JSONResponse(status_code=422, content={"detail": "입력값 오류", "errors": exc.errors})

    @app.exception_handler(MonthLockedError)
    async def _locked(_: Request, exc: MonthLockedError):
        return JSONResponse(status_code=423, content={"detail": str(exc)})

    @app.exception_handler(NotFoundError)
    async def _nf(_: Request, exc: NotFoundError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(LookupError)
    async def _lookup(_: Request, exc: LookupError):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ConfirmationRequired)
    async def _confirm(_: Request, exc: ConfirmationRequired):
        return JSONResponse(
            status_code=409,
            content={
                "detail": "확인이 필요합니다",
                "warnings": exc.warnings,
                "open_holds": exc.open_holds,
                "unresolved": exc.unresolved,
            },
        )

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    app.include_router(_router(service), prefix="/api")
    return app


def _router(svc: SettlementService) -> APIRouter:
    r = APIRouter()

    # ── 메타 ──
    @r.get("/meta")
    def meta(user: User = Depends(current_user)):
        return {
            "user": {"email": user.email, "is_approver": user.is_approver},
            "categories": {k.value: v for k, v in CATEGORY_LABELS.items()},
            "tags": {k.value: v for k, v in TAG_LABELS.items()},
            "exception_types": [
                {"value": t.value, "label": EXCEPTION_TYPE_LABELS[t], "required": REQUIRED_FIELDS[t]}
                for t in ExceptionType
            ],
            "exception_statuses": {k.value: v for k, v in EXCEPTION_STATUS_LABELS.items()},
            "rules": dump(svc.cfg),
        }

    @r.get("/plants")
    def plants(q: str = "", user: User = Depends(current_user)):
        items = sorted(svc.repos.source.plants().values(), key=lambda p: p.plant_id)
        if q:
            ql = q.lower()
            items = [p for p in items if ql in p.plant_id.lower() or ql in p.name.lower()]
        return dump(items[:50])

    # ── ① 데이터 불러오기 ──
    @r.post("/months/{month}/load")
    def load(month: str, user: User = Depends(current_user)):
        return {"month": month, "counts": svc.load_counts(month), "locked": svc.is_locked(month)}

    @r.get("/months/{month}/status")
    def status(month: str, user: User = Depends(current_user)):
        approval = svc.repos.approvals.get(month)
        run = svc.repos.runs.latest(month)
        return {
            "month": month,
            "locked": approval is not None,
            "approval": dump(approval),
            "latest_run_id": run.run_id if run else None,
            "category_counts": run.by_category() if run else None,
        }

    # ── ③ 3자 대조 ──
    @r.post("/months/{month}/runs")
    def run(month: str, user: User = Depends(current_user)):
        res = svc.run(month, user.email)
        return _run_json(res)

    @r.get("/months/{month}/runs/latest")
    def latest(month: str, user: User = Depends(current_user)):
        return _run_json(svc.latest_run(month))

    @r.post("/runs/{run_id}/automation/preview")
    def preview(run_id: str, body: PlantIdsIn, user: User = Depends(current_user)):
        return dump(svc.preview_automation(run_id, body.plant_ids))

    @r.post("/runs/{run_id}/automation/execute")
    def execute(run_id: str, body: PlantIdsIn, user: User = Depends(current_user)):
        records = svc.execute_automation(run_id, user.email, body.plant_ids)
        return {"rechecks": dump(records), "run": _run_json(svc.latest_run(svc.repos.runs.get(run_id).month))}

    # ── ④ 확인 대상 ──
    @r.get("/months/{month}/plants/{plant_id}")
    def detail(month: str, plant_id: str, user: User = Depends(current_user)):
        return dump(svc.plant_detail(month, plant_id))

    @r.post("/months/{month}/plants/{plant_id}/recheck")
    def recheck(month: str, plant_id: str, user: User = Depends(current_user)):
        return dump(svc.recheck(month, plant_id, user.email))

    @r.post("/months/{month}/plants/{plant_id}/hold")
    def hold(month: str, plant_id: str, body: HoldIn, user: User = Depends(current_user)):
        return dump(svc.hold(month, plant_id, body.reason, user.email))

    @r.delete("/months/{month}/plants/{plant_id}/hold")
    def release(month: str, plant_id: str, user: User = Depends(current_user)):
        return dump(svc.release_hold(month, plant_id, user.email))

    # ── ② 예외 관리 ──
    @r.get("/exceptions")
    def list_exceptions(
        month: Optional[str] = Query(default=None),
        plant_id: Optional[str] = Query(default=None),
        user: User = Depends(current_user),
    ):
        return dump(svc.repos.exceptions.list(month=month, plant_id=plant_id))

    @r.post("/exceptions", status_code=201)
    def create_exception(body: ExceptionIn, user: User = Depends(current_user)):
        return dump(svc.create_exception(_to_exception(body), user.email))

    @r.put("/exceptions/{exception_id}")
    def update_exception(exception_id: str, body: ExceptionIn, user: User = Depends(current_user)):
        return dump(svc.update_exception(_to_exception(body, exception_id), user.email))

    @r.post("/exceptions/{exception_id}/close")
    def close_exception(exception_id: str, user: User = Depends(current_user)):
        return dump(svc.close_exception(exception_id, user.email))

    @r.get("/exceptions/{exception_id}/history")
    def exception_history(exception_id: str, user: User = Depends(current_user)):
        return dump(svc.repos.exceptions.history(exception_id))

    # ── 에러 케이스 ──
    @r.get("/error-cases")
    def list_error_cases(month: Optional[str] = Query(default=None), user: User = Depends(current_user)):
        return dump(svc.repos.error_cases.list(month))

    @r.post("/error-cases", status_code=201)
    def add_error_case(body: ErrorCaseIn, user: User = Depends(current_user)):
        case = ErrorCase(case_no="", occurred_on=body.occurred_on, month=body.month, plant_id=body.plant_id, symptom=body.symptom)
        return dump(svc.add_error_case(case, user.email))

    # ── 확정 ──
    @r.post("/months/{month}/finalize")
    def finalize(month: str, body: FinalizeIn, user: User = Depends(current_user)):
        if not user.is_approver:
            raise HTTPException(status_code=403, detail="확정 권한이 없습니다")
        return dump(svc.finalize(month, user.email, body.acknowledge, body.note))

    # ── ⑤ 리포트 ──
    @r.get("/months/{month}/report")
    def report(month: str, kind: str = "monthly", user: User = Depends(current_user)):
        if kind not in ("monthly", "unresolved"):
            raise HTTPException(status_code=400, detail="kind 는 monthly | unresolved")
        return build_report(svc, month, kind)

    return r


def _run_json(run) -> dict:
    data = dump(run)
    data["category_counts"] = run.by_category()
    return data


app = create_app()
