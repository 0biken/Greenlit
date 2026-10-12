"""The defect status service (M5-03, M5-04, M5-05, M5-06, M5-08): every transition in
DATA §7, and the rule that nothing else changes the two statuses."""

import ast
from pathlib import Path

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError
from tests.lab import Lab

from apps.core.models import AuditEvent
from apps.core.services import ServiceError
from apps.defects import status
from apps.defects.models import Defect, Retest
from apps.runs.models import Evidence, EvidenceLink

pytestmark = pytest.mark.django_db


@pytest.fixture
def lab():
    return Lab()


def test_a_new_defect_is_open_and_not_retested(lab):
    d = lab.defect()
    assert (d.tracker_status, d.qa_status, status.shown_as(d)) == ("open", "not_retested", "Open")
    assert d.display_no == 1


# --- Rule 1: fixed ---------------------------------------------------------------------------


def test_marking_fixed_records_when_and_who_and_asks_for_a_retest(lab):
    d = lab.set(lab.defect(), "fixed")
    assert d.fixed_at is not None and d.fixed_by_id == lab.developer.pk
    assert (d.tracker_status, d.qa_status, status.shown_as(d)) == (
        "fixed",
        "not_retested",
        "Needs retest",
    )


def test_fixing_again_after_a_failed_retest_resets_it_to_not_retested(lab):
    d = lab.retest(lab.set(lab.defect(), "fixed"), "failed")
    assert (d.tracker_status, d.qa_status, status.shown_as(d)) == (
        "open",
        "retest_failed",
        "Reopened",
    )
    d = lab.set(d, "fixed")
    assert (d.tracker_status, d.qa_status) == ("fixed", "not_retested")


# --- Rule 2: retests -------------------------------------------------------------------------


def test_a_passed_retest_verifies_the_defect_and_keeps_its_evidence(lab):
    d = lab.retest(lab.set(lab.defect(), "fixed"), "passed")
    assert (d.tracker_status, d.qa_status, status.shown_as(d)) == ("fixed", "verified", "Verified")
    with lab.scope():
        retest = Retest.objects.get(defect=d)
        assert retest.tested_by_id == lab.tester.pk
        evidence = Evidence.objects.get()
        targets = set(
            EvidenceLink.objects.filter(evidence=evidence).values_list("target_type", "target_id")
        )
        assert targets == {("retest", retest.pk), ("defect", d.pk)}


def test_a_failed_retest_reopens_the_defect_in_the_tracker(lab):
    d = lab.retest(lab.set(lab.defect(), "fixed"), "failed")
    assert (d.tracker_status, d.qa_status) == ("open", "retest_failed")


@pytest.mark.parametrize("outcome", ["passed", "failed"])
def test_a_retest_without_evidence_is_refused(lab, outcome):
    d = lab.set(lab.defect(), "fixed")
    with pytest.raises(ServiceError) as error:
        lab.retest(d, outcome, files=[])
    assert error.value.code == "evidence"
    with lab.scope():
        assert not Retest.objects.exists()
        assert Defect.objects.get(pk=d.pk).qa_status == "not_retested"


def test_a_refused_file_cannot_be_used_as_evidence(lab):
    d = lab.set(lab.defect(), "fixed")
    bad = lab.file()
    with lab.scope():
        type(bad).objects.filter(pk=bad.pk).update(state="infected")
    with pytest.raises(ServiceError):
        lab.retest(d, "passed", files=[bad])
    with lab.scope():
        assert not Retest.objects.exists() and not Evidence.objects.exists()


def test_a_defect_that_is_not_fixed_cannot_be_retested(lab):
    with pytest.raises(ServiceError):
        lab.retest(lab.defect(), "passed")


def test_each_retest_is_its_own_row(lab):
    d = lab.retest(lab.set(lab.defect(), "fixed"), "failed")
    d = lab.retest(lab.set(d, "fixed"), "passed")
    with lab.scope():
        assert list(Retest.objects.order_by("tested_at").values_list("outcome", flat=True)) == [
            "failed",
            "passed",
        ]
    assert d.qa_status == "verified"


def test_the_database_refuses_to_change_or_delete_a_retest(lab):
    d = lab.retest(lab.set(lab.defect(), "fixed"), "passed")
    with lab.scope(), connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")
        for sql in ("UPDATE defects_retest SET outcome = 'failed'", "DELETE FROM defects_retest"):
            with pytest.raises(DatabaseError), transaction.atomic():
                cursor.execute(sql)
        cursor.execute("RESET ROLE")
    assert d.qa_status == "verified"


# --- M5-08: the fixer cannot verify -------------------------------------------------------------


def test_the_person_who_fixed_it_cannot_be_the_one_to_verify_it(lab):
    d = lab.set(lab.defect(), "fixed", actor=lab.tester)
    with pytest.raises(ServiceError) as error:
        lab.retest(d, "passed", actor=lab.tester)
    assert error.value.code == "fixer"
    assert lab.retest(d, "passed", actor=lab.lead).qa_status == "verified"


def test_the_fixer_may_still_report_that_the_fix_failed(lab):
    d = lab.set(lab.defect(), "fixed", actor=lab.tester)
    assert lab.retest(d, "failed", actor=lab.tester).qa_status == "retest_failed"


def test_the_fixer_rule_can_be_switched_off_per_project(lab):
    with lab.scope():
        lab.project.settings = {"fixer_cannot_verify": False}
        lab.project.save()
    d = lab.set(lab.defect(), "fixed", actor=lab.tester)
    assert lab.retest(d, "passed", actor=lab.tester).qa_status == "verified"


# --- Rule 3: reopening -----------------------------------------------------------------------


@pytest.mark.parametrize("back_to", ["open", "in_progress"])
def test_reopening_a_verified_defect_resets_it_and_counts_as_a_reopen(lab, back_to):
    d = lab.retest(lab.set(lab.defect(), "fixed"), "passed")
    d = lab.set(d, back_to)
    assert (d.tracker_status, d.qa_status) == (back_to, "not_retested")
    with lab.scope():
        assert AuditEvent.objects.filter(action="defect.reopened", target_id=str(d.pk)).count() == 1


def test_reopening_an_unverified_fix_is_not_counted_as_a_reopen(lab):
    d = lab.set(lab.set(lab.defect(), "fixed"), "open")
    assert d.qa_status == "not_retested"
    with lab.scope():
        assert not AuditEvent.objects.filter(action="defect.reopened").exists()


# --- Closed states (the rest of the DATA §7 table) ----------------------------------------------


def test_closed_without_a_retest_still_needs_one(lab):
    d = lab.set(lab.set(lab.defect(), "fixed"), "closed")
    assert d.closed_at is not None
    assert (d.qa_status, status.shown_as(d)) == ("not_retested", "Closed, unverified")


def test_closing_after_a_failed_retest_is_the_critical_state(lab):
    d = lab.retest(lab.set(lab.defect(), "fixed"), "failed")
    d = lab.set(d, "closed")
    assert (d.tracker_status, d.qa_status, status.shown_as(d)) == (
        "closed",
        "retest_failed",
        "Closed, retest failed",
    )


def test_a_closed_defect_can_be_retested_and_verified(lab):
    d = lab.set(lab.set(lab.defect(), "fixed"), "closed")
    assert status.shown_as(lab.retest(d, "passed")) == "Verified"


# --- Rule 4: won't fix and deferred -------------------------------------------------------------


@pytest.mark.parametrize("decision,label", [("wont_fix", "Won't fix"), ("deferred", "Deferred")])
def test_wont_fix_and_deferred_need_a_reason_and_record_who_decided(lab, decision, label):
    d = lab.defect()
    with lab.scope():
        with pytest.raises(ServiceError):
            status.decide(d, lab.lead, decision, "  ")
        d = status.decide(d, lab.lead, decision, "Client accepted it")
    assert (d.qa_status, d.decided_by_id, d.decision_reason) == (
        decision,
        lab.lead.pk,
        "Client accepted it",
    )
    assert status.shown_as(d) == label


# --- Audit and the one-writer rule --------------------------------------------------------------


def test_every_status_change_is_audited_with_only_the_changed_fields(lab):
    d = lab.retest(lab.set(lab.defect(), "fixed"), "failed")
    with lab.scope():
        events = list(AuditEvent.objects.filter(target_id=str(d.pk)).order_by("at"))
    assert [e.action for e in events] == [
        "defect.created",
        "defect.status_changed",
        "defect.retested",
    ]
    fixed, retested = events[1], events[2]
    assert fixed.before == {"tracker_status": "open"} and fixed.after == {"tracker_status": "fixed"}
    assert retested.before == {"tracker_status": "fixed", "qa_status": "not_retested"}
    assert (
        retested.after["tracker_status"] == "open"
        and retested.after["qa_status"] == "retest_failed"
    )


STATUS_FIELDS = {"tracker_status", "qa_status"}
WRITING_CALLS = {"create", "update", "get_or_create", "update_or_create", "bulk_create", "Defect"}


def status_writes(source: str) -> list[int]:
    """Line numbers where code sets a defect status: `x.qa_status = ...`, or passes one of the
    two fields to create(), update() or Defect(). Reading and filtering are not writes."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Attribute) and t.attr in STATUS_FIELDS for t in targets):
                lines.append(node.lineno)
        elif isinstance(node, ast.Call):
            name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
            if name in WRITING_CALLS and any(k.arg in STATUS_FIELDS for k in node.keywords):
                lines.append(node.lineno)
    return lines


def test_only_the_status_service_writes_the_two_statuses():
    """M5-03: outside `apps/defects/status.py`, no code sets `tracker_status` or `qa_status`.
    Tests and migrations are exempt."""
    apps = Path(__file__).resolve().parents[2]
    offenders = []
    for path in apps.rglob("*.py"):
        relative = path.relative_to(apps).as_posix()
        if "/tests/" in relative or "/migrations/" in relative or relative == "defects/status.py":
            continue
        offenders += [f"{relative}:{n}" for n in status_writes(path.read_text(encoding="utf-8"))]
    assert offenders == []


def test_the_guard_itself_spots_a_write():
    assert status_writes("defect.qa_status = 'verified'") == [1]
    assert status_writes("Defect.objects.filter(pk=1).update(tracker_status='closed')") == [1]
    assert status_writes("Defect.objects.create(title='x', qa_status='verified')") == [1]
    assert (
        status_writes("Defect.objects.filter(qa_status='verified').exclude(tracker_status='open')")
        == []
    )
    assert status_writes("qa_status = serializers.CharField()") == []


# --- The API ---------------------------------------------------------------------------------


def test_the_api_marks_fixed_and_records_a_retest_by_display_id(lab):
    d = lab.defect()
    fixed = lab.call(
        lab.developer, "post", f"/api/projects/lab/defects/BUG-{d.display_no}/fixed/", {}
    )
    assert fixed.status_code == 200 and fixed.json()["shown_as"] == "Needs retest"

    url = f"/api/projects/lab/defects/{d.display_no}/retests/"
    none = lab.call(lab.tester, "post", url, {"outcome": "passed", "evidence_file_ids": []})
    assert none.status_code == 400 and none.json()["code"] == "evidence"

    ok = lab.call(
        lab.tester, "post", url, {"outcome": "passed", "evidence_file_ids": [str(lab.file().pk)]}
    )
    assert ok.status_code == 201
    assert ok.json() == {
        "display_id": f"BUG-{d.display_no}",
        "tracker_status": "fixed",
        "qa_status": "verified",
        "shown_as": "Verified",
    }


def test_a_developer_can_mark_fixed_but_cannot_record_a_retest(lab):
    d = lab.set(lab.defect(), "fixed")
    url = f"/api/projects/lab/defects/{d.pk}/retests/"
    body = {"outcome": "passed", "evidence_file_ids": [str(lab.file().pk)]}
    assert lab.call(lab.developer, "post", url, body).status_code == 403
    assert (
        lab.call(lab.viewer, "post", f"/api/projects/lab/defects/{d.pk}/fixed/", {}).status_code
        == 403
    )


def test_an_unknown_defect_or_project_is_not_found(lab):
    assert (
        lab.call(lab.tester, "post", "/api/projects/lab/defects/999/fixed/", {}).status_code == 404
    )
    assert (
        lab.call(lab.tester, "post", "/api/projects/nope/defects/1/fixed/", {}).status_code == 404
    )
