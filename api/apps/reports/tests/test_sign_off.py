"""Sign-off (M8-06, UX Flow 3): a named person's approval, with readiness at that moment and
a report that is frozen from then on."""

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError
from tests.lab import Lab

from apps.core.models import AuditEvent, Membership, Role
from apps.core.services import ServiceError
from apps.reports import services
from apps.reports.models import Report, SignOff
from apps.runs.models import Release

pytestmark = pytest.mark.django_db
URL = "/api/projects/lab/releases/1.0/sign-off/"


class Blocked(Lab):
    """A release that is not ready: one fix is waiting for its retest."""

    def __init__(self):
        super().__init__()
        self.release_ = self.release("1.0")
        requirement = self.requirement()
        _, version, _ = self.plan(cases=[("Pays by card", [requirement])])
        self.run(self.release_, version, ["passed"])
        self.waiting = self.set(self.defect(release=self.release_), "fixed")


@pytest.fixture
def lab():
    return Blocked()


def detail(lab, user=None):
    return lab.call(user or lab.viewer, "get", "/api/projects/lab/releases/1.0/").json()


def refused(fn):
    with pytest.raises(DatabaseError), transaction.atomic():
        fn()


# --- Not ready: a reason is required -


@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "   "}, {"reason": None}])
def test_signing_off_while_not_ready_needs_a_written_reason(lab, body):
    response = lab.call(lab.lead, "post", URL, body)
    assert response.status_code == 400 and response.json()["code"] == "reason"
    with lab.scope():
        assert not SignOff.objects.exists() and not Report.objects.exists()
        assert Release.objects.get(pk=lab.release_.pk).state == "open"


def test_with_a_reason_it_is_recorded_with_who_when_and_the_readiness_then(lab):
    response = lab.call(lab.lead, "post", URL, {"reason": "Client accepted the open risk."})
    assert response.status_code == 200
    body = response.json()
    assert body["sign_off"]["by"] == "qa_lead"
    assert body["sign_off"]["readiness"] == "not_ready"
    assert body["sign_off"]["reason"] == "Client accepted the open risk."
    assert body["report"]["state"] == "signed" and body["report"]["display_id"] == "RPT-001"
    with lab.scope():
        record = SignOff.objects.get()
        assert (record.signed_by_id, record.readiness_at_signing) == (lab.lead.pk, "not_ready")
        assert Release.objects.get(pk=lab.release_.pk).state == "signed_off"
        event = AuditEvent.objects.get(action="release.signed_off")
        assert event.after["readiness"] == "not_ready" and event.after["override"] is True


def test_a_ready_release_needs_no_reason_and_stores_none(lab):
    lab.retest(lab.waiting, "passed")
    response = lab.call(lab.lead, "post", URL, {"reason": "not needed"})
    assert response.status_code == 200
    assert response.json()["sign_off"] == {
        "by": "qa_lead",
        "at": response.json()["sign_off"]["at"],
        "readiness": "ready",
        "reason": None,
    }


def test_readiness_is_recomputed_at_the_moment_of_signing(lab):
    """The page may be stale: what counts is the state when the button is pressed."""
    lab.retest(lab.waiting, "passed")  # ready now
    lab.set(lab.defect("New critical", severity="critical", release=lab.release_), "in_progress")
    assert lab.call(lab.lead, "post", URL, {}).json()["code"] == "reason"


# --- Who may sign -


@pytest.mark.parametrize("role", [Role.QA_ENGINEER, Role.DEVELOPER, Role.VIEWER])
def test_only_owners_admins_and_leads_can_sign_off(lab, role):
    assert lab.call(lab.users[role], "post", URL, {"reason": "x"}).status_code == 403
    with lab.scope():
        assert not SignOff.objects.exists()


@pytest.mark.parametrize("role", [Role.OWNER, Role.ADMIN, Role.QA_LEAD])
def test_owners_admins_and_leads_can(lab, role):
    assert lab.call(lab.users[role], "post", URL, {"reason": "Accepted"}).status_code == 200


def test_the_role_is_checked_again_inside_the_service(lab):
    """A membership object fetched before a demotion must not carry the old right."""
    stale = lab.membership(lab.lead)
    with lab.scope():
        Membership.objects.filter(pk=stale.pk).update(role=Role.VIEWER)
        fresh = Membership.objects.select_related("user").get(pk=stale.pk)
        with pytest.raises(ServiceError) as error:
            services.sign_off(lab.release_, fresh, "Accepted")
    assert error.value.code == "forbidden"


def test_a_release_is_signed_off_once(lab):
    assert lab.call(lab.lead, "post", URL, {"reason": "Accepted"}).status_code == 200
    again = lab.call(lab.owner, "post", URL, {"reason": "Again"})
    assert again.status_code == 400 and again.json()["code"] == "conflict"
    with lab.scope():
        assert SignOff.objects.count() == 1


# --- The frozen report -


def test_viewing_a_release_stores_nothing(lab):
    assert detail(lab)["report"]["state"] == "draft"
    with lab.scope():
        assert not Report.objects.exists()


def test_the_signed_report_does_not_change_when_things_change_later(lab):
    signed = lab.call(lab.lead, "post", URL, {"reason": "Accepted"}).json()
    assert "Not ready yet. 1 blocker remains." in signed["report"]["summary"]
    lab.retest(lab.waiting, "passed")
    after = detail(lab)
    # Readiness is live; the report and the sign-off are the record of what was signed.
    assert (after["readiness"], after["blockers"]) == ("ready", [])
    assert after["report"] == signed["report"]
    assert after["sign_off"] == signed["sign_off"]
    assert after["sign_off"]["readiness"] == "not_ready"


def test_the_database_refuses_changes_to_a_signed_report_and_to_the_sign_off(lab):
    lab.call(lab.lead, "post", URL, {"reason": "Accepted"})
    with lab.scope():
        report = Report.objects.get()
        refused(lambda: Report.objects.filter(pk=report.pk).update(body={"summary": "Rewritten"}))
        refused(lambda: Report.objects.filter(pk=report.pk).update(state="draft"))
        with connection.cursor() as cursor:
            cursor.execute("SET LOCAL ROLE greenlit_app")
            for sql in (
                "UPDATE reports_signoff SET override_reason = 'x'",
                "DELETE FROM reports_signoff",
            ):
                with pytest.raises(DatabaseError), transaction.atomic():
                    cursor.execute(sql)
            cursor.execute("RESET ROLE")
        assert Report.objects.get().body["summary"].startswith("100% of requirements")


def test_the_database_itself_requires_a_reason_when_not_ready(lab):
    lab.call(lab.lead, "post", URL, {"reason": "Accepted"})
    with lab.scope():
        first = SignOff.objects.get()
        refused(
            lambda: SignOff.objects.create(
                org_id=lab.id,
                release=lab.release_,
                report=first.report,
                signed_by=lab.lead,
                signed_at=first.signed_at,
                readiness_at_signing="not_ready",
                override_reason="",
            )
        )
