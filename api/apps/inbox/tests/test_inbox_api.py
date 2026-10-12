"""The QA Inbox and snoozing (M6-03, M6-04, FR-INB-01, FR-INB-04), through the API."""

from datetime import timedelta

import pytest
from django.utils import timezone
from tests.lab import Lab, days_ago

from apps.core.models import AuditEvent
from apps.inbox.models import Snooze
from apps.reports.facts import build_facts

pytestmark = pytest.mark.django_db


class Busy(Lab):
    """A project with one of each kind of thing the Inbox shows."""

    def __init__(self):
        super().__init__()
        self.release_ = self.release("2.4.1")
        self.uncovered = self.requirement("Refund to the original card", priority="critical")
        covered = self.requirement("Pay by card")
        _, version, _ = self.plan(
            cases=[("Pays by card", [covered]), ("Guest checkout", [covered])]
        )
        _, results = self.run(
            self.release_, version, ["passed"]
        )  # the second case is never run: stale
        self.fresh = self.backdate(
            self.set(self.defect("Fixed yesterday", release=self.release_), "fixed"),
            fixed_at=days_ago(1),
        )
        self.old = self.backdate(
            self.set(self.defect("Fixed five days ago", release=self.release_), "fixed"),
            fixed_at=days_ago(5),
        )
        failed = self.retest(
            self.set(self.defect("Closed but broken", release=self.release_), "fixed"), "failed"
        )
        self.critical = self.set(failed, "closed")

    def inbox(self, user, query=""):
        response = self.call(user, "get", f"/api/inbox/{query}")
        assert response.status_code == 200, response.content
        return response.json()

    def shown(self, user, query=""):
        return [i["display_id"] for i in self.inbox(user, query)["items"]]


@pytest.fixture
def lab():
    return Busy()


# --- Who sees what (DATA §9) -----------------------------------------------------------------


def test_the_owner_of_a_defect_sees_it_at_once_critical_first(lab):
    body = lab.inbox(lab.tester)
    assert [i["display_id"] for i in body["items"]] == ["BUG-3", "BUG-2", "BUG-1", "TC-0002"]
    first = body["items"][0]
    assert (first["critical"], first["group"], first["status"]) == (
        True,
        "closed_failed_retest",
        "retest_failed",
    )
    assert body["counts"] == {
        "closed_failed_retest": 1,
        "needs_retest": 2,
        "aging_defects": 0,
        "unfiled_failures": 0,
        "missing_evidence": 0,
        "stale_tests": 1,
        "uncovered": 0,
    }


def test_a_lead_sees_needs_retest_only_after_the_second_escalation_time(lab):
    # Fixed 5 days ago is past 96 hours; fixed yesterday is not.
    assert lab.shown(lab.lead) == ["BUG-3", "BUG-2", "TC-0002", "REQ-1"]
    with lab.scope():
        lab.project.settings = {"retest_escalation_hours": [12, 20]}
        lab.project.save()
    assert "BUG-1" in lab.shown(lab.lead)


def test_owners_and_admins_see_what_a_lead_sees(lab):
    assert lab.shown(lab.owner) == lab.shown(lab.users["admin"]) == lab.shown(lab.lead)


def test_developers_and_viewers_have_an_empty_inbox_and_see_the_next_release(lab):
    for user in (lab.developer, lab.viewer):
        body = lab.inbox(user)
        assert body["items"] == [] and sum(body["counts"].values()) == 0
        assert (
            body["next_release"]["version"] == "2.4.1"
            and body["next_release"]["project_key"] == "LAB"
        )


def test_failures_go_to_whoever_recorded_them(lab):
    _, version, _ = lab.plan(title="Cart", cases=[("Empties the cart", [])])
    lab.run(lab.release("2.5.0"), version, ["failed"])
    mine = lab.inbox(lab.tester)
    assert mine["counts"]["unfiled_failures"] == 1 and mine["counts"]["missing_evidence"] == 1
    assert lab.inbox(lab.lead)["counts"]["unfiled_failures"] == 0


def test_an_item_carries_its_age_project_and_single_next_action(lab):
    item = next(i for i in lab.inbox(lab.tester)["items"] if i["display_id"] == "BUG-2")
    assert (item["age_days"], item["next_action"], item["project_key"], item["owner_name"]) == (
        5,
        "retest",
        "LAB",
        "qa_engineer",
    )
    assert item["id"] == f"defect.{lab.old.pk}"


def test_people_not_on_a_project_do_not_see_its_items(lab):
    outsider = lab.add("qa_lead")
    with lab.scope():
        from apps.core.models import ProjectMember

        ProjectMember.objects.filter(user=outsider).delete()
    assert lab.shown(outsider) == []


# --- Snoozing ----------------------------------------------------------------------------------


def snooze(lab, user, item_id, days=2, reason="Waiting for staging"):
    until = (timezone.now() + timedelta(days=days)).isoformat()
    return lab.call(
        user, "post", f"/api/inbox/{item_id}/snooze/", {"reason": reason, "until": until}
    )


def test_a_snoozed_item_leaves_the_inbox_and_shows_under_snoozed(lab):
    key = f"defect.{lab.old.pk}"
    assert snooze(lab, lab.tester, key).status_code == 204
    body = lab.inbox(lab.tester)
    assert "BUG-2" not in [i["display_id"] for i in body["items"]]
    assert (body["snoozed"], body["counts"]["needs_retest"]) == (1, 1)
    (hidden,) = lab.inbox(lab.tester, "?snoozed=1")["items"]
    assert (hidden["display_id"], hidden["snooze_reason"]) == ("BUG-2", "Waiting for staging")
    assert hidden["snoozed_until"] is not None
    with lab.scope():
        assert AuditEvent.objects.filter(action="inbox.snoozed", target_id=str(lab.old.pk)).exists()


def test_a_snooze_is_personal(lab):
    snooze(lab, lab.tester, f"defect.{lab.old.pk}")
    assert "BUG-2" in lab.shown(lab.lead)


def test_a_snoozed_item_still_blocks_the_release(lab):
    for d in (lab.fresh, lab.old, lab.critical):
        for user in (lab.tester, lab.lead):
            assert snooze(lab, user, f"defect.{d.pk}").status_code == 204
    assert not [i for i in lab.inbox(lab.tester)["items"] if i["display_id"].startswith("BUG")]
    with lab.scope():
        facts = build_facts(lab.release_)
    assert facts.readiness == "not_ready"
    assert {b.display_id for b in facts.blockers} >= {"BUG-1", "BUG-2", "BUG-3"}


def test_a_snooze_ends_by_itself_or_when_removed(lab):
    key = f"defect.{lab.old.pk}"
    snooze(lab, lab.tester, key)
    assert lab.call(lab.tester, "post", f"/api/inbox/{key}/unsnooze/", {}).status_code == 204
    assert "BUG-2" in lab.shown(lab.tester)
    # Removing a snooze that is not there is harmless.
    assert lab.call(lab.tester, "post", f"/api/inbox/{key}/unsnooze/", {}).status_code == 204

    snooze(lab, lab.tester, key)
    with lab.scope():
        Snooze.objects.update(until=timezone.now() - timedelta(minutes=1))
    assert "BUG-2" in lab.shown(lab.tester)
    assert lab.inbox(lab.tester)["snoozed"] == 0


def test_snoozing_again_replaces_the_earlier_snooze(lab):
    key = f"defect.{lab.old.pk}"
    snooze(lab, lab.tester, key, reason="First")
    assert snooze(lab, lab.tester, key, reason="Second").status_code == 204
    (hidden,) = lab.inbox(lab.tester, "?snoozed=1")["items"]
    assert hidden["snooze_reason"] == "Second"


@pytest.mark.parametrize("days,reason", [(2, "  "), (-1, "Past"), (120, "Too far")])
def test_a_snooze_needs_a_reason_and_a_date_within_90_days(lab, days, reason):
    assert (
        snooze(lab, lab.tester, f"defect.{lab.old.pk}", days=days, reason=reason).status_code == 400
    )
    assert lab.inbox(lab.tester)["snoozed"] == 0


@pytest.mark.parametrize(
    "item_id",
    [
        "defect.00000000-0000-0000-0000-000000000000",
        "defect.not-a-uuid",
        "nonsense",
        "organisation.x",
    ],
)
def test_snoozing_something_that_is_not_there_is_not_found(lab, item_id):
    assert snooze(lab, lab.tester, item_id).status_code == 404
