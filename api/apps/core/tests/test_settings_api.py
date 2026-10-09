"""Managing members, invitations and projects after creation (M1-19), as the restricted app role."""

import uuid

import pytest
from django.db import connection
from django.test import Client

from apps.core import services
from apps.core.models import (
    AuditEvent,
    Invitation,
    Membership,
    MembershipStatus,
    Organisation,
    Project,
    ProjectMember,
    Role,
    User,
)
from apps.core.project_settings import DEFAULTS, project_settings
from apps.core.tenancy import org_scope

pytestmark = pytest.mark.django_db
JSON = "application/json"


class Org:
    """An organisation with one person per role, and a project the engineer is on."""

    def __init__(self, slug: str):
        self.id = uuid.uuid4()
        self.slug = slug
        with org_scope(self.id):
            Organisation.objects.create(id=self.id, name=slug.title(), slug=slug)
            self.project = Project.objects.create(org_id=self.id, name="Portal", key="PRJ")
        self.users = {role: self.add(role) for role in Role.values}
        with org_scope(self.id):
            ProjectMember.objects.create(
                org_id=self.id, project=self.project, user=self.users[Role.QA_ENGINEER]
            )

    def add(self, role: str, email: str | None = None) -> User:
        user = User.objects.create_user(email or f"{role}-{uuid.uuid4().hex[:6]}@x.test", "x" * 14)
        with org_scope(self.id):
            Membership.objects.create(
                org_id=self.id, user=user, role=role, status=MembershipStatus.ACTIVE
            )
        return user

    def as_(self, role_or_user) -> Client:
        user = self.users[role_or_user] if isinstance(role_or_user, str) else role_or_user
        client = Client()
        client.force_login(user)
        return client

    def call(self, who, method: str, path: str, body=None):
        kwargs: dict = {"headers": {"X-Org": self.slug}}
        if body is not None:
            kwargs.update(data=body, content_type=JSON)
        return getattr(self.as_(who), method)(path, **kwargs)

    def role_of(self, user: User) -> str:
        with org_scope(self.id):
            return Membership.objects.get(user=user).role

    def events(self, action: str):
        with org_scope(self.id):
            return list(AuditEvent.objects.filter(action=action))


@pytest.fixture
def org():
    made = Org("acme")
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")
    return made


def member_url(user: User) -> str:
    return f"/api/members/{user.id}/"


# --- Roles ------------------------------------------------------------------------------------


def test_an_owner_changes_a_role_and_it_is_audited(org):
    engineer = org.users[Role.QA_ENGINEER]
    response = org.call(Role.OWNER, "patch", member_url(engineer), {"role": "qa_lead"})
    assert response.status_code == 200 and response.json()["role"] == "qa_lead"
    assert org.role_of(engineer) == "qa_lead"
    (event,) = org.events("member.role_changed")
    assert (event.before, event.after) == ({"role": "qa_engineer"}, {"role": "qa_lead"})


def test_an_admin_manages_everyone_below_owner(org):
    lead = org.users[Role.QA_LEAD]
    assert org.call(Role.ADMIN, "patch", member_url(lead), {"role": "viewer"}).status_code == 200
    other_admin = org.add(Role.ADMIN)
    assert (
        org.call(Role.ADMIN, "patch", member_url(other_admin), {"role": "developer"}).status_code
        == 200
    )


def test_only_an_owner_can_make_or_unmake_an_owner(org):
    owner, lead = org.users[Role.OWNER], org.users[Role.QA_LEAD]
    assert org.call(Role.ADMIN, "patch", member_url(lead), {"role": "owner"}).status_code == 403
    assert org.call(Role.ADMIN, "patch", member_url(owner), {"role": "viewer"}).status_code == 403
    assert org.call(Role.ADMIN, "delete", member_url(owner)).status_code == 403
    assert org.role_of(owner) == "owner"
    assert org.call(Role.OWNER, "patch", member_url(lead), {"role": "owner"}).status_code == 200


def test_the_last_owner_cannot_be_demoted_or_removed(org):
    owner = org.users[Role.OWNER]
    demote = org.call(Role.OWNER, "patch", member_url(owner), {"role": "admin"})
    assert demote.status_code == 400 and demote.json()["code"] == "last_owner"
    remove = org.call(Role.OWNER, "delete", member_url(owner))
    assert remove.status_code == 400 and remove.json()["code"] == "last_owner"

    second = org.add(Role.OWNER)
    assert org.call(Role.OWNER, "patch", member_url(owner), {"role": "admin"}).status_code == 200
    assert org.role_of(second) == "owner"


def test_an_admin_can_step_down_but_then_has_no_admin_rights(org):
    admin = org.users[Role.ADMIN]
    assert org.call(Role.ADMIN, "patch", member_url(admin), {"role": "viewer"}).status_code == 200
    lead = org.users[Role.QA_LEAD]
    assert org.call(admin, "patch", member_url(lead), {"role": "viewer"}).status_code == 403


def test_an_admin_cannot_make_themselves_an_owner(org):
    admin = org.users[Role.ADMIN]
    assert org.call(Role.ADMIN, "patch", member_url(admin), {"role": "owner"}).status_code == 403
    assert org.role_of(admin) == "admin"


def test_an_unchanged_role_writes_no_audit_entry(org):
    lead = org.users[Role.QA_LEAD]
    assert org.call(Role.OWNER, "patch", member_url(lead), {"role": "qa_lead"}).status_code == 200
    assert org.events("member.role_changed") == []


def test_an_invalid_role_is_refused(org):
    lead = org.users[Role.QA_LEAD]
    assert org.call(Role.OWNER, "patch", member_url(lead), {"role": "superuser"}).status_code == 400


# --- Removing people --------------------------------------------------------------------------


def test_a_removed_member_loses_this_organisation_and_keeps_their_others(org):
    engineer = org.users[Role.QA_ENGINEER]
    elsewhere = Org("elsewhere")
    with org_scope(elsewhere.id):
        Membership.objects.create(
            org_id=elsewhere.id, user=engineer, role=Role.VIEWER, status=MembershipStatus.ACTIVE
        )
    assert org.call(Role.ADMIN, "delete", member_url(engineer)).status_code == 204

    assert org.call(engineer, "get", "/api/org/").status_code == 404
    assert elsewhere.call(engineer, "get", "/api/org/").status_code == 200
    listed = [m["user_id"] for m in org.call(Role.OWNER, "get", "/api/members/").json()]
    assert str(engineer.id) not in listed
    with org_scope(org.id):
        assert Membership.all_objects.get(user=engineer).status == "removed"  # kept, not deleted
        assert not ProjectMember.objects.filter(user=engineer).exists()
    (event,) = org.events("member.removed")
    assert event.after == {"status": "removed"}


def test_removing_twice_or_removing_a_stranger_is_not_found(org):
    engineer = org.users[Role.QA_ENGINEER]
    org.call(Role.ADMIN, "delete", member_url(engineer))
    assert org.call(Role.ADMIN, "delete", member_url(engineer)).status_code == 404
    stranger = User.objects.create_user("stranger@x.test", "x" * 14)
    assert org.call(Role.ADMIN, "delete", member_url(stranger)).status_code == 404
    assert (
        org.call(Role.ADMIN, "patch", member_url(stranger), {"role": "viewer"}).status_code == 404
    )


# --- Invitations ------------------------------------------------------------------------------


def invite(org, email="new@x.test", role="viewer"):
    with org_scope(org.id):
        owner = Membership.objects.get(user=org.users[Role.OWNER])
        org_row = Organisation.objects.get(pk=org.id)
        return services.invite_member(owner, org_row, email, role)


def test_pending_invitations_are_listed_and_can_be_revoked(org, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        pending = invite(org)
    listed = org.call(Role.ADMIN, "get", "/api/invites/").json()
    assert [(i["email"], i["invited_by"]) for i in listed] == [
        ("new@x.test", org.users[Role.OWNER].email)
    ]

    assert org.call(Role.ADMIN, "delete", f"/api/invites/{pending.id}/").status_code == 204
    assert org.call(Role.ADMIN, "get", "/api/invites/").json() == []
    assert org.call(Role.ADMIN, "delete", f"/api/invites/{pending.id}/").status_code == 404
    with org_scope(org.id):
        assert Invitation.objects.get(pk=pending.id).revoked_at is not None
    assert len(org.events("invitation.revoked")) == 1


def test_a_revoked_invitation_cannot_be_accepted(org, django_capture_on_commit_callbacks):
    from django.core import mail
    from tests.support import latest_link_key

    with django_capture_on_commit_callbacks(execute=True):
        pending = invite(org, "late@x.test")
    token = latest_link_key("/invite/")
    org.call(Role.OWNER, "delete", f"/api/invites/{pending.id}/")

    late = User.objects.create_user("late@x.test", "x" * 14)
    from allauth.account.models import EmailAddress

    EmailAddress.objects.create(user=late, email=late.email, verified=True, primary=True)
    client = Client()
    client.force_login(late)
    accepted = client.post("/api/invites/accept/", data={"token": token}, content_type=JSON)
    assert accepted.status_code == 400
    assert mail.outbox  # the invitation was really sent before it was revoked


# --- Projects ---------------------------------------------------------------------------------


def test_a_project_shows_its_settings_with_defaults(org):
    body = org.call(Role.QA_ENGINEER, "get", "/api/projects/prj/").json()
    assert body["settings"] == DEFAULTS


def test_an_admin_renames_a_project_and_changes_its_client(org):
    response = org.call(
        Role.ADMIN, "patch", "/api/projects/prj/", {"name": "Portal 2", "client_name": "Hube Ltd"}
    )
    assert response.status_code == 200
    assert (response.json()["name"], response.json()["client_name"]) == ("Portal 2", "Hube Ltd")
    (event,) = org.events("project.updated")
    assert event.before == {"name": "Portal", "client_name": ""}


def test_settings_are_changed_partially_and_audited(org):
    response = org.call(
        Role.OWNER, "patch", "/api/projects/prj/", {"settings": {"stale_after_days": 14}}
    )
    assert response.status_code == 200
    settings = response.json()["settings"]
    assert settings["stale_after_days"] == 14
    assert settings["retest_escalation_hours"] == [48, 96]  # untouched keys keep their values
    with org_scope(org.id):
        assert project_settings(Project.objects.get(key="PRJ"))["stale_after_days"] == 14
    (event,) = org.events("project.settings_changed")
    assert event.after["settings"]["stale_after_days"] == 14


@pytest.mark.parametrize(
    "change",
    [
        {"stale_after_days": 0},
        {"stale_after_days": 400},
        {"stale_after_days": "30"},
        {"stale_after_days": True},
        {"retest_escalation_hours": [96, 48]},
        {"retest_escalation_hours": [48]},
        {"aging_days": {"critical": 2, "high": 7, "medium": 14}},
        {"aging_days": {"critical": 0, "high": 7, "medium": 14, "low": 30}},
        {"fixer_cannot_verify": "yes"},
        {"something_else": 1},
    ],
)
def test_invalid_settings_are_refused_and_nothing_changes(org, change):
    response = org.call(Role.OWNER, "patch", "/api/projects/prj/", {"settings": change})
    assert response.status_code == 400
    with org_scope(org.id):
        assert Project.objects.get(key="PRJ").settings == {}


def test_engineers_cannot_change_a_project(org):
    assert (
        org.call(Role.QA_ENGINEER, "patch", "/api/projects/prj/", {"name": "Mine"}).status_code
        == 403
    )


def test_adding_and_removing_project_members_changes_what_they_can_see(org):
    newcomer = org.add(Role.QA_ENGINEER)
    assert org.call(newcomer, "get", "/api/projects/prj/").status_code == 404

    added = org.call(
        Role.ADMIN, "post", "/api/projects/prj/members/", {"user_id": str(newcomer.id)}
    )
    assert added.status_code == 204
    assert org.call(newcomer, "get", "/api/projects/prj/").status_code == 200
    on_project = [
        m["user_id"] for m in org.call(Role.ADMIN, "get", "/api/projects/prj/members/").json()
    ]
    assert str(newcomer.id) in on_project

    removed = org.call(Role.ADMIN, "delete", f"/api/projects/prj/members/{newcomer.id}/")
    assert removed.status_code == 204
    assert org.call(newcomer, "get", "/api/projects/prj/").status_code == 404
    assert [e.action for e in org.events("project.member_added")] == ["project.member_added"]
    assert len(org.events("project.member_removed")) == 1


def test_someone_removed_from_a_project_can_be_added_back(org):
    """The membership row is kept when removed, so adding back must restore it."""
    engineer = org.users[Role.QA_ENGINEER]
    org.call(Role.ADMIN, "delete", f"/api/projects/prj/members/{engineer.id}/")
    again = org.call(
        Role.ADMIN, "post", "/api/projects/prj/members/", {"user_id": str(engineer.id)}
    )
    assert again.status_code == 204
    assert org.call(engineer, "get", "/api/projects/prj/").status_code == 200


def test_only_active_organisation_members_can_join_a_project(org):
    stranger = User.objects.create_user("outsider@x.test", "x" * 14)
    response = org.call(
        Role.ADMIN, "post", "/api/projects/prj/members/", {"user_id": str(stranger.id)}
    )
    assert response.status_code == 404
    not_on_it = org.users[Role.VIEWER]
    assert (
        org.call(Role.ADMIN, "delete", f"/api/projects/prj/members/{not_on_it.id}/").status_code
        == 404
    )
