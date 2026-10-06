"""HTTP API (Node/TS 화면 연동) 계약."""
from __future__ import annotations

import io
import zipfile

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from dxfcheck.samples import build_pv_set  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DXFCHECK_JOBS_DIR", str(tmp_path / "jobs"))
    from dxfcheck.api import app

    return TestClient(app)


@pytest.fixture
def bad_zip(tmp_path):
    d = build_pv_set(tmp_path / "pv", bad=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for f in sorted(d.glob("*.dxf")):
            zf.write(f, "pv/" + f.name)
    return buf.getvalue()


def test_full_flow(client, bad_zip):
    r = client.post("/api/validate", files={"file": ("세트.zip", bad_zip, "application/zip")}, data={"llm": "off"})
    assert r.status_code == 200, r.text
    body = r.json()
    job, rep = body["job_id"], body["report"]
    items = rep["packages"][0]["items21"]
    assert len(items) == 21 and items[0]["no"] == "E-01" and items[6]["status"] == "누락"
    assert rep["verdict"] == "부적합"
    f = next(x for f in [rep["packages"][0]["findings"]] for x in f if x["rule_id"] == "SET-E04-3")
    assert f["fixable"] and f["id"]

    fb = client.post("/api/jobs/%s/feedback" % job, json={"items": [
        {"finding_id": f["id"], "decision": "reject"},
        {"finding_id": "nope", "decision": "accept"}]}).json()
    assert fb["saved"] == 1 and fb["errors"]

    rd = client.post("/api/jobs/%s/redesign" % job, json={"max_rounds": 3}).json()
    assert rd["status"] in ("개선", "통과")
    assert rd["after"]["counts"]["error"] < rd["before"]["counts"]["error"]
    assert not any(c["rule_id"] == "SET-E04-3" for c in rd["changes"])          # 거부한 수정은 안 함
    assert len(rd["after"]["items21"]) == 21

    dl = client.get(rd["download_url"])
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(dl.content)).namelist()
    assert "reports/redesign.md" in names and any(n.startswith("design/pv/") for n in names)

    again = client.post("/api/jobs/%s/redesign" % job, json={}).json()      # 이어서 재설계
    assert again["before"]["counts"]["error"] == rd["after"]["counts"]["error"]
    assert client.get("/api/jobs/%s" % job).json()["job"]["state"] == "redesigned"


def test_errors(client):
    assert client.get("/api/jobs/../../etc").status_code in (400, 404)
    assert client.get("/api/jobs/abcdefabcdef").status_code == 404
    assert client.post("/api/validate", files={"file": ("a.txt", b"x", "text/plain")}).status_code == 400


def test_llm_unavailable_falls_back(client, bad_zip, monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY_SECRET", raising=False)
    r = client.post("/api/validate", files={"file": ("s.zip", bad_zip, "application/zip")}, data={"llm": "gemini"})
    assert r.status_code == 200 and "LLM 연결 실패" in r.json()["warning"]
