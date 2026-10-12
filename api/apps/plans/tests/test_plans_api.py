"""Plans, drafts, cases, diff and roll back through the API (M3-02 to M3-07, M3-10)."""

import pytest
from tests.lab import Lab

from apps.plans.models import CaseRevision, PlanVersion, PlanVersionCase, TestCase

pytestmark = pytest.mark.django_db
P = "/api/projects/lab"
CASE = {"title": "Pays by card", "steps": ["Open checkout", "Pay"], "expected": "Order placed."}


class Published(Lab):
    """A plan at version 1.0 with two cases, the first covering REQ-1."""

    def __init__(self):
        super().__init__()
        self.req = self.requirement("Pay by card")
        self.plan_, self.v1, _ = self.plan(
            cases=[("Pays by card", [self.req]), ("Card declined", [])]
        )


@pytest.fixture
def lab():
    return Published()


def post(lab, path, body=None, user=None):
    return lab.call(user or lab.tester, "post", f"{P}/plans/1/{path}", body or {})


def patch(lab, case, body, user=None):
    return lab.call(user or lab.tester, "patch", f"{P}/plans/1/draft/cases/{case}/", body)


def cases(lab, version="draft"):
    return lab.call(lab.viewer, "get", f"{P}/plans/1/versions/{version}/").json()["cases"]


def plan(lab):
    return lab.call(lab.viewer, "get", f"{P}/plans/1/").json()


# --- A new plan, from nothing to version 1.0 -----------------------------------------------------


def test_a_new_plan_goes_from_an_empty_draft_to_version_one():
    lab = Lab()
    lab.requirement("Pay by card")
    made = lab.call(lab.tester, "post", f"{P}/plans/", {"title": "Checkout"})
    assert made.status_code == 201
    body = made.json()
    assert (body["display_id"], body["version"], body["draft"]["cases"]) == ("TP-1", None, 0)
    assert [u["display_id"] for u in body["uncovered"]] == ["REQ-1"]

    # Nothing to submit or approve until it has a case.
    assert post(lab, "draft/submit/").status_code == 400
    assert post(lab, "draft/approve/", user=lab.lead).status_code == 400

    added = post(lab, "draft/cases/", {**CASE, "requirements": [1]})
    assert added.status_code == 201
    (case,) = added.json()["cases"]
    assert (case["case"], case["revision"], case["steps"]) == ("TC-0001", 1, CASE["steps"])
    assert [r["display_id"] for r in case["requirements"]] == ["REQ-1"]

    assert post(lab, "draft/submit/").json()["draft"]["submitted_by"] == "qa_engineer"
    # A QA engineer writes and submits; only a lead approves (FR-PLAN-05).
    assert post(lab, "draft/approve/").status_code == 403
    approved = post(lab, "draft/approve/", user=lab.lead).json()
    assert (approved["version"], approved["draft"], approved["uncovered"]) == ("1.0", None, [])
    assert [(v["number"], v["state"], v["approved_by"]) for v in approved["versions"]] == [
        ("1.0", "published", "qa_lead")
    ]
    rows = lab.call(lab.viewer, "get", f"{P}/plans/").json()
    assert [(r["display_id"], r["version"], r["cases"], r["has_draft"]) for r in rows] == [
        ("TP-1", "1.0", 1, False)
    ]


def test_a_case_is_validated_on_save(lab):
    post(lab, "draft/")
    for bad in (
        {**CASE, "title": " "},
        {**CASE, "steps": []},
        {**CASE, "steps": ["", " "]},
        {**CASE, "expected": " "},
        {**CASE, "priority": "urgent"},
        {**CASE, "requirements": [99]},
    ):
        assert post(lab, "draft/cases/", bad).status_code == 400, bad
    assert patch(lab, "TC-0001", {"title": " "}).status_code == 400
    assert len(cases(lab)) == 2


def test_developers_and_viewers_cannot_change_a_plan(lab):
    for user in (lab.developer, lab.viewer):
        assert post(lab, "draft/", user=user).status_code == 403
    post(lab, "draft/")
    for user in (lab.developer, lab.viewer):
        assert post(lab, "draft/cases/", CASE, user=user).status_code == 403
        assert patch(lab, 1, {"title": "No"}, user=user).status_code == 403
        assert lab.call(user, "delete", f"{P}/plans/1/draft/").status_code == 403
        assert post(lab, "versions/1.0/roll-back/", user=user).status_code == 403
        assert lab.call(user, "get", f"{P}/plans/1/").json()["actions"] == {
            "edit": False,
            "approve": False,
        }


# --- Editing a published plan (FR-TC-02; DATA "Versioning") --------------------------------------


def test_opening_a_draft_copies_pointers_and_no_content(lab):
    with lab.scope():
        revisions = CaseRevision.objects.count()
    opened = post(lab, "draft/")
    assert opened.status_code == 201 and opened.json()["draft"]["cases"] == 2
    assert [(c["case"], c["revision"]) for c in cases(lab)] == [("TC-0001", 1), ("TC-0002", 1)]
    with lab.scope():
        assert CaseRevision.objects.count() == revisions
    # One draft per plan: opening it again answers with the draft that is already there.
    assert post(lab, "draft/", user=lab.lead).status_code == 200
    with lab.scope():
        assert PlanVersion.objects.filter(state="draft").count() == 1


def test_an_edit_makes_a_new_revision_and_leaves_the_published_one_alone(lab):
    post(lab, "draft/")
    edited = patch(lab, "TC-0001", {"title": "Pays by saved card", "steps": ["Pay", "Confirm"]})
    assert edited.status_code == 200
    first = edited.json()["cases"][0]
    assert (first["revision"], first["title"], first["steps"]) == (
        2,
        "Pays by saved card",
        ["Pay", "Confirm"],
    )
    assert [r["display_id"] for r in first["requirements"]] == ["REQ-1"]  # links carry over
    assert cases(lab, "1.0")[0]["title"] == "Pays by card"

    # A second edit in the same draft changes revision 2 in place: nothing else uses it yet.
    again = patch(lab, 1, {"expected": "Order placed and emailed."}).json()["cases"][0]
    assert (again["revision"], again["expected"]) == (2, "Order placed and emailed.")
    # Saving it unchanged does nothing.
    assert (
        patch(lab, 1, {"expected": "Order placed and emailed."}).json()["cases"][0]["revision"] == 2
    )
    with lab.scope():
        assert CaseRevision.objects.filter(test_case__display_no=1).count() == 2


def test_a_revision_a_run_used_is_never_edited_in_place(lab):
    lab.run(lab.release(), lab.v1, ["passed", "passed"])
    post(lab, "draft/")
    patch(lab, 1, {"title": "Pays by saved card"})
    post(lab, "draft/approve/", user=lab.lead)
    run = lab.call(lab.viewer, "get", f"{P}/runs/1/").json()
    assert [c["title"] for c in run["cases"]] == ["Pays by card", "Card declined"]


def test_removing_a_case_drops_the_pointer_and_keeps_the_case(lab):
    post(lab, "draft/")
    left = lab.call(lab.tester, "delete", f"{P}/plans/1/draft/cases/TC-0001/")
    assert [c["case"] for c in left.json()["cases"]] == ["TC-0002"]
    assert lab.call(lab.viewer, "get", f"{P}/cases/1/").status_code == 200
    assert len(cases(lab, "1.0")) == 2
    # It is no longer in the draft, so there is nothing there to edit or remove.
    assert patch(lab, 1, {"title": "Gone"}).status_code == 404


def test_cases_can_be_reordered_in_a_draft(lab):
    post(lab, "draft/")
    post(lab, "draft/cases/", {**CASE, "title": "Guest checkout"})
    moved = patch(lab, 3, {"position": 1}).json()["cases"]
    assert [c["title"] for c in moved] == ["Guest checkout", "Pays by card", "Card declined"]
    assert [c["title"] for c in cases(lab, "1.0")] == ["Pays by card", "Card declined"]


def test_any_edit_withdraws_a_submission(lab):
    post(lab, "draft/")
    patch(lab, 1, {"title": "Pays by saved card"})
    assert post(lab, "draft/submit/").json()["draft"]["submitted_at"] is not None
    patch(lab, 2, {"title": "Card is declined"})
    assert plan(lab)["draft"]["submitted_at"] is None


def test_discarding_a_draft_removes_only_what_the_draft_made(lab):
    post(lab, "draft/")
    patch(lab, 1, {"title": "Pays by saved card"})
    post(lab, "draft/cases/", {**CASE, "title": "Guest checkout"})
    with lab.scope():
        assert (CaseRevision.objects.count(), TestCase.objects.count()) == (4, 3)

    gone = lab.call(lab.tester, "delete", f"{P}/plans/1/draft/")
    assert gone.status_code == 200 and gone.json()["draft"] is None
    with lab.scope():
        assert (CaseRevision.objects.count(), TestCase.objects.count()) == (2, 2)
        assert not PlanVersion.objects.filter(state="draft").exists()
    assert [c["title"] for c in cases(lab, "1.0")] == ["Pays by card", "Card declined"]
    assert lab.call(lab.viewer, "get", f"{P}/cases/3/").status_code == 404
    assert lab.call(lab.tester, "delete", f"{P}/plans/1/draft/").status_code == 404
    assert post(lab, "draft/").status_code == 201  # and a fresh draft can be opened


def test_a_plan_that_was_never_published_keeps_an_empty_draft_when_discarded():
    lab = Lab()
    lab.call(lab.tester, "post", f"{P}/plans/", {"title": "Checkout"})
    post(lab, "draft/cases/", CASE)
    body = lab.call(lab.tester, "delete", f"{P}/plans/1/draft/").json()
    assert body["draft"] == {"cases": 0, "submitted_by": None, "submitted_at": None}
    with lab.scope():
        assert not PlanVersionCase.objects.exists() and not TestCase.objects.exists()


# --- Stale, and how an edit clears it (FR-TC-05) ------------------------------------------------


def test_saving_a_case_against_the_new_requirement_text_clears_stale(lab):
    lab.call(lab.tester, "patch", f"{P}/requirements/1/", {"text": "Card or wallet."})
    assert cases(lab, "1.0")[0]["requirements"][0]["stale"] is True
    post(lab, "draft/")
    renewed = patch(lab, 1, {"requirements": [1]}).json()["cases"][0]
    assert (renewed["revision"], renewed["requirements"][0]["stale"]) == (2, False)
    post(lab, "draft/approve/", user=lab.lead)
    assert lab.call(lab.viewer, "get", f"{P}/requirements/1/").json()["stale_cases"] == 0
    # The old version still says what it was written against.
    assert cases(lab, "1.0")[0]["requirements"][0]["stale"] is True


# --- Diff (FR-TC-03) -----------------------------------------------------------------------------


def test_the_diff_lists_added_removed_and_changed_cases_down_to_the_step(lab):
    post(lab, "draft/")
    patch(
        lab,
        1,
        {"title": "Pays by saved card", "steps": ["Sign in", "Do it"], "priority": "high"},
    )
    lab.call(lab.tester, "delete", f"{P}/plans/1/draft/cases/2/")
    post(lab, "draft/cases/", {**CASE, "title": "Guest checkout"})
    post(lab, "draft/approve/", user=lab.lead)

    diff = lab.call(lab.viewer, "get", f"{P}/plans/1/diff/?from=1.0&to=1.1").json()
    assert [c["case"] for c in diff["added"]] == ["TC-0003"]
    assert [c["case"] for c in diff["removed"]] == ["TC-0002"]
    (changed,) = diff["changed"]
    assert changed["case"] == "TC-0001"
    assert {c["field"]: (c["before"], c["after"]) for c in changed["changes"]} == {
        "title": ("Pays by card", "Pays by saved card"),
        "priority": ("medium", "high"),
    }
    assert [(s["op"], s["text"]) for s in changed["steps"]] == [
        ("added", "Sign in"),
        ("same", "Do it"),
    ]
    assert (diff["unchanged_count"], diff["unchanged"]) == (0, [])
    assert lab.call(lab.viewer, "get", f"{P}/plans/1/diff/?from=1.0&to=9.9").status_code == 404


def test_unchanged_cases_are_counted_and_hidden_unless_asked_for(lab):
    post(lab, "draft/")
    patch(lab, 1, {"title": "Pays by saved card"})
    hidden = lab.call(lab.viewer, "get", f"{P}/plans/1/diff/?from=1.0&to=draft").json()
    assert (hidden["unchanged_count"], hidden["unchanged"]) == (1, [])
    shown = lab.call(lab.viewer, "get", f"{P}/plans/1/diff/?from=1.0&to=draft&unchanged=1").json()
    assert [c["case"] for c in shown["unchanged"]] == ["TC-0002"]


# --- Roll back (FR-TC-04) ------------------------------------------------------------------------


def test_rolling_back_publishes_a_new_version_equal_to_the_old_one(lab):
    post(lab, "draft/")
    patch(lab, 1, {"title": "Pays by saved card"})
    post(lab, "draft/approve/", user=lab.lead)

    assert post(lab, "versions/1.0/roll-back/").status_code == 403  # leads only
    assert post(lab, "versions/1.1/roll-back/", user=lab.lead).status_code == 400  # already current
    back = post(lab, "versions/1.0/roll-back/", user=lab.lead)
    assert back.status_code == 200
    assert [(v["number"], v["state"]) for v in back.json()["versions"]] == [
        ("1.2", "published"),
        ("1.1", "superseded"),
        ("1.0", "superseded"),
    ]
    assert cases(lab, "1.2") == cases(lab, "1.0")
    assert cases(lab, "1.1")[0]["title"] == "Pays by saved card"  # history is kept
    diff = lab.call(lab.viewer, "get", f"{P}/plans/1/diff/?from=1.0&to=1.2").json()
    assert (diff["added"], diff["removed"], diff["changed"]) == ([], [], [])


def test_a_plan_with_a_draft_cannot_be_rolled_back(lab):
    post(lab, "draft/")
    patch(lab, 1, {"title": "Pays by saved card"})
    post(lab, "draft/approve/", user=lab.lead)
    post(lab, "draft/")
    refused = post(lab, "versions/1.0/roll-back/", user=lab.lead)
    assert refused.status_code == 400 and "draft" in refused.json()["detail"]


# --- One case ------------------------------------------------------------------------------------


def test_a_case_page_shows_what_it_says_where_it_is_used_and_how_it_went(lab):
    lab.run(lab.release(), lab.v1, ["failed"])
    post(lab, "draft/")
    patch(lab, 1, {"title": "Pays by saved card"})
    body = lab.call(lab.viewer, "get", f"{P}/cases/TC-0001/").json()
    # What a tester would run today is the published revision, not the draft's.
    assert (body["case"], body["title"], body["revision"]) == ("TC-0001", "Pays by card", 1)
    assert [(p["display_id"], p["version"], p["revision"]) for p in body["plans"]] == [
        ("TP-1", None, 2),
        ("TP-1", "1.0", 1),
    ]
    assert [r["revision"] for r in body["revisions"]] == [2, 1]
    assert [(r["run"], r["outcome"]) for r in body["results"]] == [("RUN-001", "failed")]
    assert lab.call(lab.viewer, "get", f"{P}/cases/99/").status_code == 404
