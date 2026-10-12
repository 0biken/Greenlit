"""PDF export and share links for signed reports (M8-07, M8-08, FR-RPT-04, SEC §4)."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone
from tests.lab import Lab

from apps.core.models import AuditEvent, Role
from apps.core.services import hash_token
from apps.reports.models import ShareLink

pytestmark = pytest.mark.django_db
REL = "/api/projects/lab/releases/1.0"


class Signed(Lab):
    """A release signed off while not ready, with one fix still waiting for its retest."""

    def __init__(self, slug="lab", key="LAB", sign=True):
        super().__init__(slug, key)
        self.release_ = self.release("1.0")
        requirement = self.requirement()
        _, version, _ = self.plan(cases=[("Pays by card", [requirement])])
        self.run(self.release_, version, ["passed"])
        self.waiting = self.set(self.defect("Payment times out", release=self.release_), "fixed")
        if sign:
            self.sign()

    def sign(self):
        base = f"/api/projects/{self.project.key.lower()}/releases/1.0"
        body = {"reason": "The client accepted the open risk in writing."}
        assert self.call(self.lead, "post", f"{base}/sign-off/", body).status_code == 200

    def link(self, user=None, **body):
        return self.call(user or self.lead, "post", f"{REL}/share-links/", body)


@pytest.fixture
def lab():
    return Signed()


def anonymous(path: str):
    return Client().get(path)


# --- The PDF -------------------------------------------------------------------------------------


def test_the_signed_report_downloads_as_a_pdf(lab):
    response = lab.call(lab.viewer, "get", f"{REL}/report.pdf")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"] == 'attachment; filename="LAB-1.0-RPT-001.pdf"'
    pdf = response.content
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    for expected in (b"Release 1.0", b"Not ready yet", b"BUG-1", b"Payment times out", b"qa_lead"):
        assert expected in pdf, expected
    assert b"The client accepted the open risk in writing." in pdf
    assert b"SIGNED OFF BY" in pdf


def test_there_is_no_pdf_until_the_release_is_signed_off():
    lab = Signed(sign=False)
    assert lab.call(lab.viewer, "get", f"{REL}/report.pdf").status_code == 404


def test_the_pdf_says_what_was_signed_even_after_things_change(lab):
    before = lab.call(lab.viewer, "get", f"{REL}/report.pdf").content
    lab.retest(lab.waiting, "passed")  # the release is ready now
    live = lab.call(lab.viewer, "get", f"{REL}/").json()
    assert live["readiness"] == "ready"
    after = lab.call(lab.viewer, "get", f"{REL}/report.pdf").content
    assert after == before  # byte for byte: the same signed report gives the same file
    assert b"Not ready yet" in after


def test_a_long_reason_is_printed_in_full():
    lab = Signed(sign=False)
    reason = " ".join(f"Sentence number {i} of the reason." for i in range(1, 41))
    lab.call(lab.lead, "post", f"{REL}/sign-off/", {"reason": reason})
    pdf = lab.call(lab.viewer, "get", f"{REL}/report.pdf").content
    assert b"number 1 of" in pdf and b"number 40 of" in pdf


# --- Making and managing links -


def test_a_lead_makes_a_link_and_the_token_is_shown_once(lab):
    made = lab.link()
    assert made.status_code == 201
    body = made.json()
    assert body["state"] == "active" and len(body["token"]) >= 40
    expires = timezone.now() + timedelta(days=30)
    assert abs((timezone.datetime.fromisoformat(body["expires_at"]) - expires).total_seconds()) < 60
    with lab.scope():
        link = ShareLink.objects.get()
        assert link.token_hash == hash_token(body["token"])
        assert body["token"] not in str(vars(link))  # only the hash is stored
        assert AuditEvent.objects.filter(action="share_link.created").count() == 1
    listed = lab.call(lab.lead, "get", f"{REL}/share-links/").json()
    assert [row["id"] for row in listed] == [body["id"]]
    assert "token" not in listed[0]


@pytest.mark.parametrize("role", [Role.QA_ENGINEER, Role.DEVELOPER, Role.VIEWER])
def test_only_leads_admins_and_owners_can_share(lab, role):
    made = lab.link().json()
    assert lab.link(user=lab.users[role]).status_code == 403
    url = f"{REL}/share-links/{made['id']}/"
    assert lab.call(lab.users[role], "delete", url).status_code == 403
    # Anyone on the project can see that links exist, but never a token.
    listed = lab.call(lab.users[role], "get", f"{REL}/share-links/")
    assert listed.status_code == 200 and "token" not in listed.json()[0]


def test_an_unsigned_release_cannot_be_shared():
    lab = Signed(sign=False)
    assert lab.link().status_code == 400
    with lab.scope():
        assert not ShareLink.objects.exists()


def test_a_link_can_last_from_1_to_365_days(lab):
    assert lab.link(days=0).status_code == 400
    assert lab.link(days=366).status_code == 400
    assert lab.link(days=7).status_code == 201


# --- Reading through a link -


def test_anyone_with_the_link_sees_the_signed_report_without_signing_in(lab):
    token = lab.link().json()["token"]
    response = anonymous(f"/api/shared/{token}/")
    assert response.status_code == 200
    body = response.json()
    assert (body["organisation"], body["project"], body["version"]) == ("Lab", "Checkout", "1.0")
    assert body["report"]["state"] == "signed" and body["report"]["display_id"] == "RPT-001"
    assert body["sign_off"]["by"] == "qa_lead" and body["sign_off"]["readiness"] == "not_ready"
    assert [b["display_id"] for b in body["blockers"]] == ["BUG-1"]
    pdf = anonymous(f"/api/shared/{token}/report.pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")


def test_a_link_never_shows_live_data(lab):
    token = lab.link().json()["token"]
    before = anonymous(f"/api/shared/{token}/").json()
    lab.retest(lab.waiting, "passed")
    lab.defect("Found after sign-off", severity="critical", release=lab.release_)
    after = anonymous(f"/api/shared/{token}/").json()
    assert after == before
    assert "Found after sign-off" not in str(after)


def test_views_and_downloads_through_a_link_are_audited(lab):
    made = lab.link().json()
    anonymous(f"/api/shared/{made['token']}/")
    anonymous(f"/api/shared/{made['token']}/report.pdf")
    with lab.scope():
        events = AuditEvent.objects.filter(target_type="share_link", target_id=made["id"])
        assert sorted(e.action for e in events) == [
            "share_link.created",
            "share_link.downloaded",
            "share_link.viewed",
        ]


def test_a_revoked_link_stops_working_at_once(lab):
    made = lab.link().json()
    path = f"/api/shared/{made['token']}/"
    assert anonymous(path).status_code == 200
    assert lab.call(lab.viewer, "delete", f"{REL}/share-links/{made['id']}/").status_code == 403
    assert lab.call(lab.lead, "delete", f"{REL}/share-links/{made['id']}/").status_code == 204
    assert anonymous(path).status_code == 404
    assert anonymous(path + "report.pdf").status_code == 404
    assert lab.call(lab.lead, "get", f"{REL}/share-links/").json()[0]["state"] == "revoked"
    # Revoking twice is harmless.
    assert lab.call(lab.lead, "delete", f"{REL}/share-links/{made['id']}/").status_code == 204


def test_an_expired_link_stops_working(lab):
    made = lab.link(days=1).json()
    with lab.scope():
        ShareLink.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    assert anonymous(f"/api/shared/{made['token']}/").status_code == 404
    assert lab.call(lab.lead, "get", f"{REL}/share-links/").json()[0]["state"] == "expired"


@pytest.mark.parametrize("token", ["nope", "a" * 43, "../../etc/passwd"])
def test_a_wrong_token_is_simply_not_found(lab, token):
    lab.link()
    assert anonymous(f"/api/shared/{token}/").status_code == 404


# --- Tenancy -


def test_a_token_opens_only_its_own_organisations_report(lab):
    other = Signed(slug="other", key="LAB")
    mine = lab.link().json()["token"]
    theirs = other.call(other.lead, "post", f"{REL}/share-links/", {}).json()["token"]
    assert anonymous(f"/api/shared/{mine}/").json()["organisation"] == "Lab"
    assert anonymous(f"/api/shared/{theirs}/").json()["organisation"] == "Other"
    # Lab's lead cannot list or revoke Other's links through Lab's own release.
    with other.scope():
        their_link = ShareLink.objects.get()
    response = lab.call(lab.lead, "delete", f"{REL}/share-links/{their_link.pk}/")
    assert response.status_code == 404
    assert anonymous(f"/api/shared/{theirs}/").status_code == 200


def test_without_the_token_the_database_shows_no_links_at_all(lab):
    """The row-level policy: a link is readable inside its organisation or by its exact hash."""
    token = lab.link().json()["token"]
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")
        cursor.execute("SELECT count(*) FROM reports_sharelink")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT set_config('app.invite_hash', %s, true)", [hash_token("wrong")])
        cursor.execute("SELECT count(*) FROM reports_sharelink")
        assert cursor.fetchone()[0] == 0
        cursor.execute("SELECT set_config('app.invite_hash', %s, true)", [hash_token(token)])
        cursor.execute("SELECT count(*) FROM reports_sharelink")
        assert cursor.fetchone()[0] == 1
        cursor.execute("SELECT set_config('app.invite_hash', '', true)")
        cursor.execute("RESET ROLE")


def test_a_share_link_does_not_name_who_owns_each_blocker(lab):
    team = lab.call(lab.viewer, "get", f"{REL}/").json()
    assert [b["owner_name"] for b in team["blockers"]] == ["qa_engineer"]
    token = lab.link().json()["token"]
    shared = anonymous(f"/api/shared/{token}/").json()
    assert [b["display_id"] for b in shared["blockers"]] == ["BUG-1"]
    assert [b["owner_name"] for b in shared["blockers"]] == [None]
