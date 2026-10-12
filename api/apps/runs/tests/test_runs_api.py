"""Releases, runs, results and evidence through the API (M4-01 to M4-07)."""

import pytest
from tests.lab import Lab

from apps.core.models import AuditEvent, Role
from apps.runs.models import CaseResult, Evidence, Release, TestRun

pytestmark = pytest.mark.django_db
P = "/api/projects/lab"


class Ready(Lab):
    """A project with a published plan of three cases and an open release."""

    def __init__(self):
        super().__init__()
        self.req = self.requirement("Pay by card")
        self.plan_, self.version, _ = self.plan(
            cases=[
                ("Pays by card", [self.req]),
                ("Card declined", [self.req]),
                ("Guest checkout", []),
            ]
        )
        self.release_ = self.release("2.4.1")

    def start(self, user=None, **extra):
        body = {"plan": self.plan_.display_no, "release": "2.4.1", **extra}
        return self.call(user or self.tester, "post", f"{P}/runs/", body)


@pytest.fixture
def lab():
    return Ready()


def put(lab, run, case, outcome, user=None, note=""):
    url = f"{P}/runs/{run['number']}/results/{case['result_id']}/"
    return lab.call(user or lab.tester, "put", url, {"outcome": outcome, "note": note})


# --- Releases and plans -------------------------------------------------------------------------


def test_releases_are_listed_created_and_cancelled(lab):
    made = lab.call(lab.tester, "post", f"{P}/releases/", {"version": "2.5.0", "due": "2026-12-01"})
    assert made.status_code == 201 and made.json()["state"] == "open"
    again = lab.call(lab.tester, "post", f"{P}/releases/", {"version": "2.5.0"})
    assert again.status_code == 400
    listed = lab.call(lab.viewer, "get", f"{P}/releases/").json()
    assert [r["version"] for r in listed] == ["2.5.0", "2.4.1"]

    assert lab.call(lab.tester, "post", f"{P}/releases/2.5.0/cancel/", {}).status_code == 403
    assert lab.call(lab.lead, "post", f"{P}/releases/2.5.0/cancel/", {}).status_code == 204
    with lab.scope():
        assert Release.objects.get(name="2.5.0").state == "cancelled"
    # A cancelled release takes no new runs.
    assert lab.start(release="2.5.0").status_code == 400


def test_only_plans_with_a_published_version_can_be_run(lab):
    lab.plan(title="Still a draft", cases=[("Unapproved", [])], approve=False)
    plans = lab.call(lab.viewer, "get", f"{P}/plans/").json()
    assert plans == [
        {"display_id": "TP-1", "number": 1, "title": "Checkout", "version": "1.0", "cases": 3}
    ]
    assert lab.start(plan=2).status_code == 400


# --- Starting a run ------------------------------------------------------------------------------


def test_a_run_is_tied_to_the_plan_version_and_every_case_starts_not_run(lab):
    response = lab.start(build="2.4.1-rc2", environment="staging")
    assert response.status_code == 201, response.content
    run = response.json()
    assert (run["display_id"], run["plan"], run["plan_version"], run["release"]) == (
        "RUN-001",
        "Checkout",
        "1.0",
        "2.4.1",
    )
    assert (run["state"], run["total"], run["not_run"], run["started_by"]) == (
        "in_progress",
        3,
        3,
        "qa_engineer",
    )
    assert [c["case"] for c in run["cases"]] == ["TC-0001", "TC-0002", "TC-0003"]
    assert run["cases"][0]["steps"] == ["Do it"] and run["cases"][0]["expected"] == "It works."


@pytest.mark.parametrize("role", [Role.DEVELOPER, Role.VIEWER])
def test_developers_and_viewers_cannot_start_runs_or_record_results(lab, role):
    run = lab.start().json()
    assert lab.start(user=lab.users[role]).status_code == 403
    assert put(lab, run, run["cases"][0], "passed", user=lab.users[role]).status_code == 403
    assert lab.call(lab.users[role], "get", f"{P}/runs/1/").status_code == 200


def test_a_run_is_found_by_number_display_id_or_uuid(lab):
    lab.start()
    with lab.scope():
        pk = TestRun.objects.get().pk
    for ident in ("1", "RUN-1", "run-001", str(pk)):
        assert lab.call(lab.viewer, "get", f"{P}/runs/{ident}/").status_code == 200, ident
    for ident in ("2", "BUG-1", "nope"):
        assert lab.call(lab.viewer, "get", f"{P}/runs/{ident}/").status_code == 404, ident


# --- Recording results ---------------------------------------------------------------------------


def test_a_result_saves_at_once_and_the_change_is_audited(lab):
    run = lab.start().json()
    saved = put(lab, run, run["cases"][0], "failed", note="Spinner for 60 seconds")
    assert saved.status_code == 200
    assert (saved.json()["outcome"], saved.json()["note"]) == ("failed", "Spinner for 60 seconds")
    assert saved.json()["recorded_at"] is not None
    put(lab, run, run["cases"][0], "passed")
    detail = lab.call(lab.viewer, "get", f"{P}/runs/1/").json()
    assert (detail["passed"], detail["failed"], detail["not_run"]) == (1, 0, 2)
    assert detail["cases"][0]["recorded_by"] == "qa_engineer"
    with lab.scope():
        events = AuditEvent.objects.filter(action="result.recorded").order_by("at")
        assert [(e.before["outcome"], e.after["outcome"]) for e in events] == [
            ("not_run", "failed"),
            ("failed", "passed"),
        ]


def test_sending_the_same_result_again_changes_nothing(lab):
    """A retried save after a dropped connection must be harmless (UX §9)."""
    run = lab.start().json()
    first = put(lab, run, run["cases"][0], "failed", note="Same").json()
    second = put(lab, run, run["cases"][0], "failed", note="Same").json()
    assert first == second
    with lab.scope():
        assert AuditEvent.objects.filter(action="result.recorded").count() == 1


def test_a_result_of_another_run_is_not_found(lab):
    first = lab.start().json()
    lab.start()
    url = f"{P}/runs/2/results/{first['cases'][0]['result_id']}/"
    assert lab.call(lab.tester, "put", url, {"outcome": "passed"}).status_code == 404
    assert put(lab, first, first["cases"][0], "maybe").status_code == 400


# --- Evidence and completing ---------------------------------------------------------------------


def attach(lab, run, case, file=None):
    url = f"{P}/runs/{run['number']}/results/{case['result_id']}/evidence/"
    return lab.call(lab.tester, "post", url, {"file_ids": [str((file or lab.file()).pk)]})


def test_evidence_is_attached_to_a_result_with_an_ev_number(lab):
    run = lab.start(environment="staging").json()
    made = attach(lab, run, run["cases"][0])
    assert made.status_code == 201 and made.json()[0]["display_id"] == "EV-0001"
    detail = lab.call(lab.viewer, "get", f"{P}/runs/1/").json()
    assert [e["name"] for e in detail["cases"][0]["evidence"]] == ["shot.png"]
    with lab.scope():
        assert Evidence.objects.get().environment == "staging"


def test_a_file_from_another_project_cannot_be_attached(lab):
    other = Lab(slug="other", key="OTH")
    run = lab.start().json()
    assert attach(lab, run, run["cases"][0], file=other.file()).status_code == 400


def test_a_run_cannot_be_completed_while_a_failure_has_no_evidence(lab):
    run = lab.start().json()
    one, two, three = run["cases"]
    put(lab, run, one, "failed")
    put(lab, run, two, "failed")
    put(lab, run, three, "passed")
    attach(lab, run, two)

    refused = lab.call(lab.tester, "post", f"{P}/runs/1/complete/", {})
    assert refused.status_code == 400
    body = refused.json()
    assert body["code"] == "evidence" and "1 failed result has no evidence" in body["detail"]
    assert body["missing"] == [
        {"result_id": one["result_id"], "case": "TC-0001", "title": "Pays by card"}
    ]
    with lab.scope():
        assert TestRun.objects.get().state == "in_progress"

    attach(lab, run, one)
    done = lab.call(lab.tester, "post", f"{P}/runs/1/complete/", {})
    assert done.status_code == 200 and done.json()["state"] == "complete"
    # Completing again is harmless; changing a result afterwards is refused.
    assert lab.call(lab.tester, "post", f"{P}/runs/1/complete/", {}).status_code == 200
    late = put(lab, run, three, "failed")
    assert late.status_code == 400 and late.json()["code"] == "complete"


def test_blocked_and_not_run_cases_do_not_stop_a_run_being_completed(lab):
    run = lab.start().json()
    put(lab, run, run["cases"][0], "blocked")
    assert lab.call(lab.tester, "post", f"{P}/runs/1/complete/", {}).status_code == 200


# --- Filing a defect from a failure (FR-RUN-04) ---------------------------------------------------


def test_a_defect_filed_from_a_failed_case_shows_on_the_run(lab):
    run = lab.start().json()
    case = run["cases"][0]
    put(lab, run, case, "failed")
    attach(lab, run, case)
    body = {"title": "Card payment fails", "found_in_result": case["result_id"]}
    filed = lab.call(lab.tester, "post", f"{P}/defects/", body).json()
    assert filed["found_in"]["run"] == "RUN-001" and filed["release"] == "2.4.1"
    assert [e["display_id"] for e in filed["evidence"]] == ["EV-0001"]

    detail = lab.call(lab.viewer, "get", f"{P}/runs/1/").json()
    assert detail["cases"][0]["defects"] == [
        {"display_id": "BUG-1", "number": 1, "shown_as": "Open", "chip": "open"}
    ]
    assert detail["cases"][1]["defects"] == []


def test_the_run_list_counts_outcomes(lab):
    run = lab.start().json()
    put(lab, run, run["cases"][0], "passed")
    put(lab, run, run["cases"][1], "blocked")
    lab.start()
    rows = lab.call(lab.viewer, "get", f"{P}/runs/").json()
    assert [r["display_id"] for r in rows] == ["RUN-002", "RUN-001"]
    first = rows[1]
    assert (first["passed"], first["blocked"], first["not_run"], first["total"]) == (1, 1, 1, 3)
    with lab.scope():
        assert CaseResult.objects.count() == 6
