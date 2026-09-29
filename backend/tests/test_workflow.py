import copy
import datetime as dt
from decimal import Decimal as D

import pytest

from settlement.adapters.memory import memory_repositories
from settlement.domain.models import Category, ErrorCase, ExceptionStatus, ExceptionType, SettlementException
from settlement.domain.validation import ValidationError
from settlement.fixtures import MONTH, demo_bundle, demo_exceptions
from settlement.workflow.service import ConfirmationRequired, MonthLockedError, SettlementService


@pytest.fixture
def svc():
    bundle = demo_bundle()
    s = SettlementService(memory_repositories({MONTH: bundle}))
    for e in demo_exceptions():
        s.create_exception(e, "fin@corp")
    return s


def cats(run):
    return {r.plant_id: r.category for r in run.results}


def test_automation_then_recheck_loop(svc):
    run = svc.run(MONTH, "fin@corp")
    preview = svc.preview_automation(run.run_id)
    assert preview.target_count == 4
    predicted = {i.plant_id: i.predicted_pass for i in preview.items}
    assert predicted == {"P004": True, "P005": True, "P006": True, "P012": False}

    records = svc.execute_automation(run.run_id, "fin@corp")
    by = {r.plant_id: r for r in records}
    assert by["P004"].passed and by["P005"].passed and by["P006"].passed
    assert not by["P012"].passed
    assert by["P012"].cause  # 실패 원인 기록
    assert all(r.trigger == "AUTOMATION" for r in records)

    latest = cats(svc.latest_run(MONTH))
    assert latest["P004"] == latest["P005"] == latest["P006"] == Category.PASS
    # 재검증 누락 0: 자동화한 건수 == 재검증 기록 건수
    assert len(records) == preview.target_count


def test_failed_automation_is_reverted_and_not_reoffered(svc):
    from settlement.engine.ledger import effective_adjustments

    run = svc.run(MONTH, "fin@corp")
    svc.execute_automation(run.run_id, "fin@corp")
    rows = [a for a in svc.repos.adjustments.list(MONTH) if a.plant_id == "P012"]
    assert len(rows) == 2 and rows[1].reverts == rows[0].adjustment_id  # 시도 + 되돌림 (감사 이력)
    assert [a for a in effective_adjustments(svc.repos.adjustments.list(MONTH)) if a.plant_id == "P012"] == []
    # 같은 보정만 다시 제안되므로 자동화 대상이 아니라 확인 대상
    r = {x.plant_id: x for x in svc.run(MONTH, "fin@corp").results}["P012"]
    assert r.category == Category.REVIEW and r.summary.startswith("자동화 후 재검증 미통과")
    assert r.invoice_kwh == D("7000")


def test_after_failed_automation_register_exception_and_pass(svc):
    """미통과 → 예외 등록 → [재검증] → 자동화 대상 전환 → 자동화 → 통과 (추정치와 이중 반영 없음)."""
    run = svc.run(MONTH, "fin@corp")
    svc.execute_automation(run.run_id, "fin@corp")
    svc.create_exception(
        SettlementException("", MONTH, "P012", ExceptionType.MANUAL_ISSUE, manual_kwh=D("3850"), partner_after="C-SOLAR1"),
        "fin@corp",
    )
    rc = svc.recheck(MONTH, "P012", "fin@corp")
    assert rc.category == Category.AUTOMATABLE
    records = svc.execute_automation(svc.latest_run(MONTH).run_id, "fin@corp", ["P012"])
    assert records[0].passed
    r = {x.plant_id: x for x in svc.latest_run(MONTH).results}["P012"]
    assert r.category == Category.PASS and r.invoice_kwh == D("10850")


def test_automation_marks_exceptions_active_and_is_idempotent(svc):
    run = svc.run(MONTH, "fin@corp")
    svc.execute_automation(run.run_id, "fin@corp")
    assert svc.repos.exceptions.get("EX-0001").status == ExceptionStatus.ACTIVE
    # 재실행해도 이미 적용된 예외는 다시 보정되지 않음
    run2 = svc.run(MONTH, "fin@corp")
    assert cats(run2)["P005"] == Category.PASS
    assert len(svc.repos.exceptions.history("EX-0001")) == 2


def test_source_data_is_never_mutated(svc):
    """운영 DB 쓰기 0: 자동화 전후 원천 묶음이 동일."""
    before = copy.deepcopy(svc.repos.source.load(MONTH))
    run = svc.run(MONTH, "fin@corp")
    svc.execute_automation(run.run_id, "fin@corp")
    after = svc.repos.source.load(MONTH)
    assert before == after


def test_hold_requires_reason_and_can_return(svc):
    svc.run(MONTH, "fin@corp")
    with pytest.raises(ValidationError):
        svc.hold(MONTH, "P008", "  ", "fin@corp")
    svc.hold(MONTH, "P008", "홈택스 원본 확인 대기", "fin@corp")
    assert cats(svc.latest_run(MONTH))["P008"] == Category.HOLD
    rec = svc.release_hold(MONTH, "P008", "fin@corp")
    assert rec.category == Category.REVIEW
    assert cats(svc.latest_run(MONTH))["P008"] == Category.REVIEW


def test_manual_recheck_counts_attempts(svc):
    svc.run(MONTH, "fin@corp")
    svc.recheck(MONTH, "P009", "fin@corp")
    rec = svc.recheck(MONTH, "P009", "fin@corp")
    assert rec.attempt == 2 and not rec.passed


def test_register_exception_then_recheck_passes(svc):
    """확인 대상 → 예외 등록 → 재검증 → 자동화 대상으로 전환 → 자동화 → 통과."""
    svc.run(MONTH, "fin@corp")
    b = svc.repos.source.load(MONTH)
    # P012 에 실제 누락분을 수기 발행 예외로 등록
    svc.create_exception(
        SettlementException("", MONTH, "P012", ExceptionType.MANUAL_ISSUE, manual_kwh=D("3850"), partner_after="C-SOLAR1"),
        "fin@corp",
    )
    run = svc.run(MONTH, "fin@corp")
    assert cats(run)["P012"] == Category.AUTOMATABLE
    records = svc.execute_automation(run.run_id, "fin@corp", ["P012"])
    assert records[0].passed


def test_finalize_warns_on_holds_and_locks_month(svc):
    run = svc.run(MONTH, "fin@corp")
    svc.execute_automation(run.run_id, "fin@corp")
    svc.hold(MONTH, "P008", "원본 확인 대기", "fin@corp")
    with pytest.raises(ConfirmationRequired) as ei:
        svc.finalize(MONTH, "boss@corp")
    assert ei.value.open_holds == ["P008"]
    approval = svc.finalize(MONTH, "boss@corp", acknowledge=True)
    assert approval.open_holds == ["P008"]

    with pytest.raises(MonthLockedError):
        svc.create_exception(
            SettlementException("", MONTH, "P001", ExceptionType.OTHER, note="x"), "fin@corp"
        )
    with pytest.raises(MonthLockedError):
        svc.hold(MONTH, "P009", "x", "fin@corp")


def test_exception_validation_by_type(svc):
    with pytest.raises(ValidationError) as ei:
        svc.create_exception(SettlementException("", MONTH, "P001", ExceptionType.TRANSFER), "fin@corp")
    assert set(ei.value.errors) == {"base_date", "partner_before", "partner_after"}

    with pytest.raises(ValidationError) as ei:
        svc.create_exception(
            SettlementException(
                "", MONTH, "P001", ExceptionType.TRANSFER, base_date=dt.date(2026, 9, 1), partner_before="A", partner_after="B"
            ),
            "fin@corp",
        )
    assert "base_date" in ei.value.errors

    with pytest.raises(ValidationError) as ei:
        svc.create_exception(SettlementException("", MONTH, "NOPE", ExceptionType.OTHER, note="x"), "fin@corp")
    assert "plant_id" in ei.value.errors


def test_exception_history_and_close(svc):
    exc = svc.repos.exceptions.get("EX-0002")
    exc.note = "수정"
    svc.update_exception(exc, "fin2@corp")
    closed = svc.close_exception("EX-0002", "fin2@corp")
    hist = svc.repos.exceptions.history("EX-0002")
    assert [h.version for h in hist] == [1, 2, 3]
    assert hist[1].updated_by == "fin2@corp" and closed.status == ExceptionStatus.CLOSED
    with pytest.raises(ValidationError):
        svc.update_exception(closed, "fin@corp")


def test_error_case_numbering(svc):
    c = svc.add_error_case(ErrorCase("", dt.date(2026, 9, 2), MONTH, "P011", "송장 미수집"), "tech@corp")
    assert c.case_no == "ERR-0001" and c.created_by == "tech@corp"
