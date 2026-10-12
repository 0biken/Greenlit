"""Requirements through the API: list, create, edit, and what a text change does (M2-08)."""

import pytest
from tests.lab import Lab

from apps.core.models import AuditEvent
from apps.requirements.models import Requirement, RequirementRevision

pytestmark = pytest.mark.django_db
P = "/api/projects/lab"


@pytest.fixture
def lab():
    return Lab()


def create(lab, user=None, **body):
    body = {"title": "Pay by card", "text": "A shopper can pay by card.", **body}
    return lab.call(user or lab.tester, "post", f"{P}/requirements/", body)


def test_a_tester_adds_a_requirement_by_hand(lab):
    made = create(lab, priority="high")
    assert made.status_code == 201
    body = made.json()
    assert (body["display_id"], body["revision"], body["origin"]) == ("REQ-1", 1, "human")
    assert (body["review_state"], body["covered"], body["priority"]) == ("accepted", False, "high")
    assert [r["revision"] for r in body["revisions"]] == [1]
    assert body["history"][0]["text"] == "added this requirement"


def test_a_requirement_needs_a_title_and_text(lab):
    assert create(lab, title=" ").status_code == 400
    assert create(lab, text="").status_code == 400
    with lab.scope():
        assert not Requirement.objects.exists()


def test_developers_and_viewers_can_read_but_not_write(lab):
    create(lab)
    for user in (lab.developer, lab.viewer):
        assert lab.call(user, "get", f"{P}/requirements/").status_code == 200
        assert lab.call(user, "get", f"{P}/requirements/1/").json()["actions"] == {"edit": False}
        assert create(lab, user=user).status_code == 403
        patch = lab.call(user, "patch", f"{P}/requirements/1/", {"title": "Changed"})
        assert patch.status_code == 403


def test_it_is_found_by_number_display_id_or_uuid_and_otherwise_not_found(lab):
    uuid = create(lab).json()["id"]
    for ident in ("1", "REQ-1", "req-1", uuid):
        assert lab.call(lab.viewer, "get", f"{P}/requirements/{ident}/").status_code == 200
    for ident in ("2", "BUG-1", "nonsense"):
        assert lab.call(lab.viewer, "get", f"{P}/requirements/{ident}/").status_code == 404


def test_the_list_filters_by_coverage_priority_and_search(lab):
    covered = lab.requirement("Pay by card")
    lab.requirement("Refund to the original card", priority="critical")
    lab.plan(cases=[("Pays by card", [covered])])

    def titles(query=""):
        rows = lab.call(lab.viewer, "get", f"{P}/requirements/{query}").json()
        return [r["title"] for r in rows]

    assert titles() == ["Pay by card", "Refund to the original card"]
    assert titles("?coverage=covered") == ["Pay by card"]
    assert titles("?coverage=uncovered") == ["Refund to the original card"]
    assert titles("?priority=critical") == ["Refund to the original card"]
    assert titles("?q=refund") == ["Refund to the original card"]
    assert titles("?q=REQ-1") == ["Pay by card"]


def test_changing_the_text_raises_the_revision_and_keeps_the_old_text(lab):
    create(lab)
    edited = lab.call(
        lab.tester,
        "patch",
        f"{P}/requirements/1/",
        {"text": "A shopper can pay by card or wallet."},
    )
    assert edited.status_code == 200
    body = edited.json()
    assert body["revision"] == 2
    assert [(r["revision"], r["text"]) for r in body["revisions"]] == [
        (2, "A shopper can pay by card or wallet."),
        (1, "A shopper can pay by card."),
    ]
    # Sending the same text again changes nothing.
    again = lab.call(
        lab.tester,
        "patch",
        f"{P}/requirements/1/",
        {"text": "A shopper can pay by card or wallet."},
    )
    assert again.json()["revision"] == 2
    with lab.scope():
        assert RequirementRevision.objects.count() == 2


def test_a_text_change_makes_the_cases_written_against_it_stale(lab):
    requirement = lab.requirement("Pay by card")
    _, version, _ = lab.plan(cases=[("Pays by card", [requirement])])
    lab.run(lab.release(), version, ["passed"])  # run today, so only the text change can stale it
    before = lab.call(lab.viewer, "get", f"{P}/requirements/1/").json()
    assert (before["covered"], before["stale_cases"]) == (True, 0)
    assert "stale_tests" not in {
        i["group"] for i in lab.call(lab.tester, "get", "/api/inbox/").json()["items"]
    }

    lab.call(lab.tester, "patch", f"{P}/requirements/1/", {"text": "Card or wallet."})

    after = lab.call(lab.viewer, "get", f"{P}/requirements/1/").json()
    assert after["stale_cases"] == 1
    assert [(c["display_id"], c["stale"]) for c in after["linked_cases"]] == [("TC-0001", True)]
    inbox = lab.call(lab.tester, "get", "/api/inbox/").json()["items"]
    assert [i["display_id"] for i in inbox if i["group"] == "stale_tests"] == ["TC-0001"]


def test_editing_the_title_or_priority_does_not_raise_the_revision(lab):
    create(lab)
    body = lab.call(
        lab.tester,
        "patch",
        f"{P}/requirements/1/",
        {"title": "Pay by card or wallet", "priority": "critical"},
    ).json()
    assert (body["title"], body["priority"], body["revision"]) == (
        "Pay by card or wallet",
        "critical",
        1,
    )
    assert body["history"][0]["text"] == "edited priority, title"


def test_the_audit_log_never_holds_the_requirements_text(lab):
    create(lab, text="SECRET-ONE")
    lab.call(lab.tester, "patch", f"{P}/requirements/1/", {"text": "SECRET-TWO", "title": "New"})
    with lab.scope():
        events = list(AuditEvent.objects.filter(target_type="requirement"))
    assert {e.action for e in events} == {
        "requirement.created",
        "requirement.edited",
        "requirement.text_changed",
    }
    assert "SECRET" not in str([(e.before, e.after) for e in events])


def test_a_requirement_made_before_revisions_were_kept_still_shows_its_text(lab):
    requirement = lab.requirement("Pay by card")
    with lab.scope():
        RequirementRevision.all_objects.filter(requirement=requirement).delete()
    body = lab.call(lab.viewer, "get", f"{P}/requirements/1/").json()
    assert [(r["revision"], r["text"]) for r in body["revisions"]] == [(1, "Pay by card")]
    edited = lab.call(lab.tester, "patch", f"{P}/requirements/1/", {"text": "Card or wallet."})
    assert [(r["revision"], r["text"]) for r in edited.json()["revisions"]] == [
        (2, "Card or wallet."),
        (1, "Pay by card"),
    ]
