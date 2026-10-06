"""HTTP API — Node/TS 화면(껍데기)이 부르는 로직 엔드포인트. GCP Cloud Run 배포용.

  POST /api/validate                 ZIP 업로드 → 검증 보고서(+ items21) · job_id
  GET  /api/jobs/{id}                 마지막 보고서 / 재설계 결과
  POST /api/jobs/{id}/feedback        지적별 피드백(accept / reject / correct) 학습
  POST /api/jobs/{id}/redesign        [재설계] 버튼: 수정 → 재검증(회귀) 반복 → 결과
  GET  /api/jobs/{id}/download        ZIP (재설계했으면 수정 도면+전후 보고서, 아니면 원본+보고서)
  GET  /healthz

환경변수
  DXFCHECK_JOBS_DIR      작업 저장 위치 (기본 /tmp/dxfcheck-jobs). Cloud Run 은 인스턴스 디스크가 휘발되므로
                         GCS 볼륨 마운트 경로를 지정한다 [미검증 · 회사 연결 예정]
  DXFCHECK_FEEDBACK      피드백 학습 파일 (기본 <JOBS_DIR>/feedback.json)
  DXFCHECK_PROFILES_DIR  학습 프로파일 폴더 (profile=<이름> → <폴더>/<이름>.json)
  DXFCHECK_CONFIG        설정 JSON
  DXFCHECK_MAX_UPLOAD_MB 업로드 상한 (기본 300)
  GEMINI_API_KEY / GEMINI_API_KEY_SECRET / GEMINI_MODEL   — llm/gemini.py
인증은 앞단(IAP·API Gateway·Node 서버)이 맡는다.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import __version__
from .analyzer import analyze_paths
from .config import Settings
from .llm import LLMSession, make_complete
from .model import Report
from .profile import Profile
from .redesign import FeedbackStore, finding_pattern, prepare, redesign, validation_zip

app = FastAPI(title="dxfcheck", version=__version__)
_ID = re.compile(r"^[0-9a-f]{12}$")
_LLM_CACHE: Dict[str, Any] = {}
_LOCK = threading.Lock()


def _jobs() -> Path:
    p = Path(os.environ.get("DXFCHECK_JOBS_DIR", "/tmp/dxfcheck-jobs"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _settings() -> Settings:
    return Settings.load(os.environ.get("DXFCHECK_CONFIG") or None)


def _feedback() -> FeedbackStore:
    return FeedbackStore.load(os.environ.get("DXFCHECK_FEEDBACK") or (_jobs() / "feedback.json"))


def _profile(name: str) -> Optional[Profile]:
    if not name:
        return None
    if not re.fullmatch(r"[\w\-가-힣]{1,64}", name):
        raise HTTPException(400, "profile 이름 형식 오류")
    d = Path(os.environ.get("DXFCHECK_PROFILES_DIR", "profiles"))
    prof = Profile.load(d / ("%s.json" % name))
    if prof is None:
        raise HTTPException(404, "프로파일 없음: %s" % name)
    return prof


def _complete(provider: str):
    """LLM complete 함수(프로세스당 1회 생성). 실패하면 (None, 사유)."""
    if provider in ("", "off"):
        return None, ""
    with _LOCK:
        if provider not in _LLM_CACHE:
            try:
                _LLM_CACHE[provider] = (make_complete(provider), "")
            except Exception as exc:  # noqa: BLE001  (키·모델 누락, 패키지 없음)
                return None, "LLM 연결 실패 — 규칙 검증만 수행: %s" % exc
        (fn, tag), _ = _LLM_CACHE[provider]
    return (fn, tag), ""


def _job(job_id: str) -> Path:
    if not _ID.match(job_id):
        raise HTTPException(400, "job_id 형식 오류")
    d = _jobs() / job_id
    if not d.exists():
        raise HTTPException(404, "작업 없음")
    return d


def _save(d: Path, name: str, data: Any) -> None:
    (d / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _load(d: Path, name: str) -> Any:
    p = d / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _index(report: Report) -> Dict[str, dict]:
    """피드백용 지적 색인: id → 학습 키 계산에 필요한 값."""
    return {f.id: {"rule_id": f.rule_id, "title": f.title, "file": f.file,
                   "handle": f.location.get("handle", ""), "evidence": f.evidence[:1],
                   "severity": f.severity.value} for f in report.all_findings()}


def _session(provider: str, settings: Settings, d: Path):
    got, warn = _complete(provider)
    if not got:
        return None, None, warn
    fn, tag = got
    return LLMSession(fn, settings, d / "llm_cache.json", tag), fn, warn


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "version": __version__}


@app.post("/api/validate")
async def validate(file: UploadFile = File(...), llm: str = Form("off"), profile: str = Form("")) -> dict:
    if not (file.filename or "").lower().endswith((".zip", ".dxf")):
        raise HTTPException(400, "ZIP 또는 DXF 파일만 받습니다")
    limit = int(os.environ.get("DXFCHECK_MAX_UPLOAD_MB", "300")) * 1024 * 1024
    job_id = uuid.uuid4().hex[:12]
    d = _jobs() / job_id
    d.mkdir(parents=True)
    src = d / ("input" + Path(file.filename or "x.zip").suffix.lower())
    size = 0
    with open(src, "wb") as out:
        while True:
            chunk = await file.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                out.close()
                shutil.rmtree(d, ignore_errors=True)
                raise HTTPException(413, "업로드 용량 초과")
            out.write(chunk)
    settings = _settings()
    working = prepare(src, d, settings)
    session, _, warn = _session(llm, settings, d)
    report = analyze_paths([working], settings, profile=_profile(profile), llm=session)
    if session:
        session.save()
    _save(d, "job.json", {"job_id": job_id, "filename": file.filename, "llm": llm, "profile": profile,
                          "state": "validated"})
    _save(d, "report.json", report.to_dict())
    _save(d, "index.json", _index(report))
    validation_zip(report, src, d / "result.zip")
    return {"job_id": job_id, "warning": warn, "report": report.to_dict(),
            "download_url": "/api/jobs/%s/download" % job_id}


@app.get("/api/jobs/{job_id}")
def job(job_id: str) -> dict:
    d = _job(job_id)
    return {"job": _load(d, "job.json"), "report": _load(d, "report.json"), "redesign": _load(d, "redesign.json")}


class FeedbackItem(BaseModel):
    finding_id: str
    decision: str              # accept | reject | correct
    correction: str = ""       # correct: 바꿀 문자 전체
    note: str = ""


class FeedbackBody(BaseModel):
    items: List[FeedbackItem]


@app.post("/api/jobs/{job_id}/feedback")
def feedback(job_id: str, body: FeedbackBody) -> dict:
    d = _job(job_id)
    idx = _load(d, "index.json") or {}
    store = _feedback()
    from .model import Category, Finding, Severity  # 지연 import (패턴 계산용 최소 Finding)

    saved, errors = 0, []
    for it in body.items:
        meta = idx.get(it.finding_id)
        if meta is None:
            errors.append({"finding_id": it.finding_id, "error": "지적 없음"})
            continue
        f = Finding(meta["rule_id"], Category.KEC, Severity(meta["severity"]), meta["title"], "",
                    location={"handle": meta["handle"]}, evidence=meta["evidence"], file=meta["file"])
        try:
            store.record(meta["rule_id"], finding_pattern(f, d / "working"), it.decision, it.correction, it.note)
            saved += 1
        except ValueError as exc:
            errors.append({"finding_id": it.finding_id, "error": str(exc)})
    store.save()
    return {"saved": saved, "errors": errors}


class RedesignBody(BaseModel):
    max_rounds: int = 3
    llm: Optional[str] = None      # 미인식 표기 해석 (기본: 검증 때 값)
    fix_llm: str = "off"           # 규칙이 못 고친 지적의 LLM 수정안 (off | gemini | vertex)


@app.post("/api/jobs/{job_id}/redesign")
def redesign_job(job_id: str, body: RedesignBody) -> dict:
    d = _job(job_id)
    meta = _load(d, "job.json") or {}
    settings = _settings()
    src = next((p for p in (d / "input.zip", d / "input.dxf") if p.exists()), None)
    if src is None:
        raise HTTPException(409, "입력 파일 없음")
    if meta.get("state") == "redesigned" and (d / "working").exists():
        # 재설계를 다시 누르면 마지막 결과에서 이어서 한다
        prev = d / "prev"
        if prev.exists():
            shutil.rmtree(prev)
        shutil.copytree(d / "working", prev)
        src = prev
    session, _, warn1 = _session(body.llm if body.llm is not None else meta.get("llm", "off"), settings, d)
    got, warn2 = _complete(body.fix_llm)
    store = _feedback()
    result = redesign(src, settings, out_zip=d / "result.zip", work_dir=d,
                      profile=_profile(meta.get("profile", "")), llm=session,
                      fix_complete=got[0] if got else None, feedback=store,
                      max_rounds=max(1, min(body.max_rounds, 10)))
    if session:
        session.save()
    data = result.to_dict()
    data["warning"] = "; ".join(w for w in (warn1, warn2) if w)
    data["download_url"] = "/api/jobs/%s/download" % job_id
    _save(d, "redesign.json", data)
    _save(d, "report.json", result.after.to_dict())
    _save(d, "index.json", _index(result.after))
    _save(d, "job.json", dict(meta, state="redesigned", status=result.status))
    return data


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str):
    d = _job(job_id)
    p = d / "result.zip"
    if not p.exists():
        raise HTTPException(404, "결과 없음")
    meta = _load(d, "job.json") or {}
    stem = Path(meta.get("filename") or "result").stem
    suffix = "_redesigned" if meta.get("state") == "redesigned" else "_report"
    return FileResponse(p, media_type="application/zip", filename="%s%s.zip" % (stem, suffix))
