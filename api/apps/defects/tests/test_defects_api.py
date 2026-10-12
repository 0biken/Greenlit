"""Defect list, detail, create, edit and actions through the API (M5-02, M5-06, M5-09)."""

import pytest
from tests.lab import Lab

from apps.core.models import AuditEvent, Role
from apps.defects.models import Defect
from apps.runs.models import EvidenceLink
from apps.runs.services import attach_evidence

pytestmark = pytest.mark.django_db
BASE = "/api/projects/lab/defects/"


@pytest.fixture
def lab():
    return Lab()


def url(defect, tail=""):
    return f"{BASE}{defect.display_no}/{tail}"


# --- Create ------------------------------------------------------------------------------------


def test_a_tester_files_a_defect_with_evidence(lab):
    release = lab.release("2.4.1")
    body = {
        "title": "Payment times out",
        "steps": "1. Pay by card",
        "expected": "Paid in 10 seconds",
        "actual": "Spinner for 60 seconds",
        "severity": "critical",
        "owner_id": str(lab.developer.pk),
        "release": "2.4.1",
        "evidence_file_ids": [str(lab.file().pk)],
    }
    response = lab.call(lab.tester, "post", BASE, body)
    assert response.status_code == 201, response.content
    data = response.json()
    assert (data["display_id"], data["severity"], data["shown_as"]) == ("BUG-1", "critical", "Open")
    assert (data["owner_name"], data["release"], data["created_by"]) == (
        "developer",
        "2.4.1",
        "qa_engineer",
    )
    assert [e["display_id"] for e in data["evidence"]] == ["EV-0001"]
    assert data["history"][0]["text"] == "filed this defect"
    with lab.scope():
        assert Defect.objects.get().release_id == release.pk


def test_a_defect_needs_a_title_and_a_known_severity(lab):
    assert lab.call(lab.tester, "post", BASE, {"title": " "}).status_code == 400
    assert (
        lab.call(lab.tester, "post", BASE, {"title": "x", "severity": "urgent"}).status_code == 400
    )
    with lab.scope():
        assert not Defect.objects.exists()


@pytest.mark.parametrize("role", [Role.DEVELOPER, Role.VIEWER])
def test_developers_and_viewers_cannot_file_or_edit(lab, role):
    d = lab.defect()
    assert lab.call(lab.users[role], "post", BASE, {"title": "x"}).status_code == 403
    assert lab.call(lab.users[role], "patch", url(d), {"title": "y"}).status_code == 403


def test_the_owner_release_and_result_must_belong_to_this_project(lab):
    other = Lab(slug="other", key="OTH")
    stranger = other.tester
    for extra in (
        {"owner_id": str(stranger.pk)},
        {"release": "9.9"},
        {"found_in_result": "00000000-0000-0000-0000-000000000000"},
    ):
        response = lab.call(lab.tester, "post", BASE, {"title": "x", **extra})
        assert response.status_code == 400, extra
    with lab.scope():
        assert not Defect.objects.exists()


def test_a_defect_filed_from_a_failed_result_carries_its_evidence_and_release(lab):
    requirement = lab.requirement("Pay by card")
    release = lab.release("2.4.1")
    _, version, _ = lab.plan(cases=[("Pays by card", [requirement])])
    run, (result,) = lab.run(release, version, ["failed"])
    with lab.scope():
        attach_evidence(lab.project, lab.tester, [lab.file().pk], [("case_result", result.pk)])
    response = lab.call(
        lab.tester, "post", BASE, {"title": "Card fails", "found_in_result": str(result.pk)}
    )
    data = response.json()
    assert data["release"] == "2.4.1"
    assert data["found_in"] == {
        "run": f"RUN-{run.display_no:03d}",
        "run_no": run.display_no,
        "case": "TC-0001",
        "case_title": "Pays by card",
        "result_id": str(result.pk),
    }
    assert data["requirements"] == [{"display_id": "REQ-1", "title": "Pay by card"}]
    assert [e["display_id"] for e in data["evidence"]] == ["EV-0001"]  # the same file, linked twice
    with lab.scope():
        assert EvidenceLink.objects.filter(target_type="defect").count() == 1


# --- List --------------------------------------------------------------------------------------


def a_mixed_bag(lab):
    lab.defect("Open low", severity="low")
    lab.set(lab.defect("Waiting"), "fixed")
    lab.retest(lab.set(lab.defect("Verified one"), "fixed"), "passed")
    lab.set(lab.retest(lab.set(lab.defect("Broken"), "fixed"), "failed"), "closed")


def titles(lab, query=""):
    response = lab.call(lab.viewer, "get", BASE + query)
    assert response.status_code == 200
    return [d["title"] for d in response.json()]


def test_the_list_puts_open_work_first(lab):
    a_mixed_bag(lab)
    assert titles(lab) == ["Broken", "Waiting", "Open low", "Verified one"]


def test_the_list_filters_by_state_severity_and_text(lab):
    a_mixed_bag(lab)
    assert titles(lab, "?state=needs_retest") == ["Waiting"]
    assert titles(lab, "?state=retest_failed") == ["Broken"]
    assert titles(lab, "?state=verified") == ["Verified one"]
    assert titles(lab, "?severity=low") == ["Open low"]
    assert titles(lab, "?q=wait") == ["Waiting"]
    assert titles(lab, "?q=BUG-3") == ["Verified one"]
    assert titles(lab, "?q=3") == ["Verified one"]


def test_a_row_carries_its_label_and_chip(lab):
    a_mixed_bag(lab)
    rows = {d["title"]: d for d in lab.call(lab.viewer, "get", BASE).json()}
    assert (rows["Broken"]["shown_as"], rows["Broken"]["chip"]) == (
        "Closed, retest failed",
        "retest_failed",
    )
    assert (rows["Waiting"]["shown_as"], rows["Waiting"]["chip"]) == (
        "Needs retest",
        "needs_retest",
    )
    assert rows["Verified one"]["chip"] == "verified"


# --- Detail and edit -----------------------------------------------------------------------------


def test_the_detail_shows_retests_newest_first_with_their_evidence(lab):
    d = lab.retest(lab.set(lab.defect(), "fixed"), "failed")
    d = lab.retest(lab.set(d, "fixed"), "passed")
    data = lab.call(lab.viewer, "get", url(d)).json()
    assert [r["outcome"] for r in data["retests"]] == ["passed", "failed"]
    assert all(len(r["evidence"]) == 1 and r["by"] == "qa_engineer" for r in data["retests"])
    assert (data["fixed_by"], data["shown_as"]) == ("developer", "Verified")
    assert [h["text"] for h in data["history"]][:2] == ["retested it: passed", "set it to fixed"]


def test_the_detail_offers_only_what_the_caller_may_do(lab):
    d = lab.set(lab.defect(), "fixed")
    actions = {
        role: lab.call(lab.users[role], "get", url(d)).json()["actions"] for role in Role.values
    }
    assert actions[Role.VIEWER] == {
        "edit": False,
        "set_status": [],
        "retest": False,
        "decide": False,
    }
    assert actions[Role.DEVELOPER]["set_status"] == ["open", "in_progress", "closed"]
    assert (actions[Role.DEVELOPER]["retest"], actions[Role.DEVELOPER]["decide"]) == (False, False)
    assert (actions[Role.QA_ENGINEER]["retest"], actions[Role.QA_ENGINEER]["decide"]) == (
        True,
        False,
    )
    assert actions[Role.QA_LEAD] == {
        "edit": True,
        "set_status": ["open", "in_progress", "closed"],
        "retest": True,
        "decide": True,
    }


def test_an_open_defect_cannot_be_retested_yet(lab):
    data = lab.call(lab.tester, "get", url(lab.defect())).json()
    assert data["actions"]["retest"] is False


def test_editing_changes_its_own_fields_and_is_audited_without_the_text(lab):
    d = lab.defect()
    response = lab.call(
        lab.tester,
        "patch",
        url(d),
        {"title": "Renamed", "actual": "A long description", "severity": "low"},
    )
    assert response.status_code == 200
    assert (response.json()["title"], response.json()["severity"]) == ("Renamed", "low")
    with lab.scope():
        event = AuditEvent.objects.get(action="defect.edited")
    assert event.after["fields"] == ["actual", "severity", "title"]
    assert "A long description" not in str(event.after) + str(event.before)


def test_editing_cannot_touch_the_two_statuses(lab):
    d = lab.defect()
    lab.call(lab.tester, "patch", url(d), {"qa_status": "verified", "tracker_status": "closed"})
    with lab.scope():
        d.refresh_from_db()
    assert (d.tracker_status, d.qa_status) == ("open", "not_retested")


# --- Actions -------------------------------------------------------------------------------------


def test_a_developer_moves_a_defect_through_the_tracker_statuses(lab):
    d = lab.defect()
    for status_, label in [
        ("in_progress", "Open"),
        ("fixed", "Needs retest"),
        ("closed", "Closed, unverified"),
    ]:
        response = lab.call(lab.developer, "post", url(d, "status/"), {"status": status_})
        assert response.status_code == 200 and response.json()["shown_as"] == label
    assert lab.call(lab.developer, "post", url(d, "status/"), {"status": "done"}).status_code == 400
    assert lab.call(lab.viewer, "post", url(d, "status/"), {"status": "open"}).status_code == 403


@pytest.mark.parametrize("decision,label", [("wont_fix", "Won't fix"), ("deferred", "Deferred")])
def test_a_lead_decides_wont_fix_or_deferred_with_a_reason(lab, decision, label):
    d = lab.defect()
    blank = lab.call(lab.lead, "post", url(d, "decision/"), {"decision": decision, "reason": ""})
    assert blank.status_code == 400
    done = lab.call(
        lab.lead,
        "post",
        url(d, "decision/"),
        {"decision": decision, "reason": "Client accepted it"},
    )
    assert done.status_code == 200 and done.json()["shown_as"] == label
    data = lab.call(lab.viewer, "get", url(d)).json()
    assert data["decision"] == {
        "decision": decision,
        "reason": "Client accepted it",
        "by": "qa_lead",
    }
    assert data["actions"]["decide"] is False


@pytest.mark.parametrize("role", [Role.QA_ENGINEER, Role.DEVELOPER, Role.VIEWER])
def test_only_leads_admins_and_owners_can_decide(lab, role):
    d = lab.defect()
    body = {"decision": "wont_fix", "reason": "No"}
    assert lab.call(lab.users[role], "post", url(d, "decision/"), body).status_code == 403


def test_verified_is_not_a_decision_anyone_can_post(lab):
    d = lab.defect()
    body = {"decision": "verified", "reason": "Trust me"}
    assert lab.call(lab.lead, "post", url(d, "decision/"), body).status_code == 400
