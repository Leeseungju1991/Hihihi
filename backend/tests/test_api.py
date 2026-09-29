import pytest
from fastapi.testclient import TestClient

from settlement.adapters.memory import memory_repositories
from settlement.api.app import create_app
from settlement.fixtures import MONTH, demo_bundle
from settlement.workflow.service import SettlementService

H = {"X-Goog-Authenticated-User-Email": "accounts.google.com:fin@corp"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("AX_DEV_USER", raising=False)
    monkeypatch.setenv("AX_APPROVERS", "boss@corp")
    svc = SettlementService(memory_repositories({MONTH: demo_bundle()}))
    return TestClient(create_app(svc, seed_demo=True))


def test_requires_identity(client):
    assert client.get("/api/meta").status_code == 401


def test_meta_exposes_required_fields(client):
    m = client.get("/api/meta", headers=H).json()
    assert m["user"] == {"email": "fin@corp", "is_approver": False}
    transfer = next(t for t in m["exception_types"] if t["value"] == "TRANSFER")
    assert transfer["required"] == ["base_date", "partner_before", "partner_after"]


def test_full_flow(client):
    assert client.post("/api/months/{}/load".format(MONTH), headers=H).json()["counts"] == {
        "journal": 13,
        "invoice": 12,
        "tax_invoice": 16,
    }
    run = client.post("/api/months/{}/runs".format(MONTH), headers=H).json()
    assert run["category_counts"] == {"PASS": 4, "AUTOMATABLE": 4, "REVIEW": 3, "HOLD": 0, "ERROR": 1}
    # 금액은 문자열(Decimal)로 직렬화
    assert isinstance(run["results"][0]["journal_amount"], str)

    pv = client.post("/api/runs/{}/automation/preview".format(run["run_id"]), json={}, headers=H).json()
    assert pv["target_count"] == 4

    ex = client.post("/api/runs/{}/automation/execute".format(run["run_id"]), json={}, headers=H).json()
    assert ex["run"]["category_counts"]["PASS"] == 7

    d = client.get("/api/months/{}/plants/P012".format(MONTH), headers=H).json()
    assert d["rechecks"][0]["passed"] is False and d["explanation"]["cause"]

    r = client.post("/api/months/{}/plants/P012/hold".format(MONTH), json={"reason": "추정치 검토 대기"}, headers=H)
    assert r.status_code == 200

    # 확정 권한 없음
    assert client.post("/api/months/{}/finalize".format(MONTH), json={}, headers=H).status_code == 403
    boss = {"X-Goog-Authenticated-User-Email": "accounts.google.com:boss@corp"}
    w = client.post("/api/months/{}/finalize".format(MONTH), json={}, headers=boss)
    assert w.status_code == 409 and w.json()["open_holds"] == ["P012"]
    ok = client.post("/api/months/{}/finalize".format(MONTH), json={"acknowledge": True}, headers=boss)
    assert ok.status_code == 200

    rep = client.get("/api/months/{}/report".format(MONTH), headers=H).json()
    assert rep["approval"]["actor"] == "boss@corp"
    assert rep["holds"][0]["reason"] == "추정치 검토 대기"
    # 미통과 추정 보정은 되돌려져 유효 0건, 리포트에는 '되돌림'으로 남음
    assert rep["estimated_count"] == 0
    assert [a["reverted"] for a in rep["automation"] if a["plant_id"] == "P012"] == [True]
    assert set(rep["applied_exception_ids"]) == {"EX-0001", "EX-0002"}

    # 확정 후 잠금
    locked = client.post(
        "/api/exceptions",
        json={"month": MONTH, "plant_id": "P001", "type": "OTHER", "note": "x"},
        headers=H,
    )
    assert locked.status_code == 423


def test_exception_validation_error_shape(client):
    r = client.post("/api/exceptions", json={"month": MONTH, "plant_id": "P001", "type": "MANUAL_ISSUE"}, headers=H)
    assert r.status_code == 422
    assert set(r.json()["errors"]) == {"manual_kwh", "partner_after"}
