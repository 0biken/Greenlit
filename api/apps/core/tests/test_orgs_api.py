"""Organisations, invitations, members and projects, end to end as the restricted app role
(FR-ORG-01 to 03, M1-08, M1-09)."""

import re
import uuid
from datetime import timedelta

import pytest
from django.core import mail
from django.db import connection
from django.test import Client
from django.utils import timezone

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
from apps.core.tenancy import org_scope, scoped, set_scope

pytestmark = pytest.mark.django_db
JSON = "application/json"


def as_app_role():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")


def as_owner_role():
    with connection.cursor() as cursor:
        cursor.execute("RESET ROLE")


def signed_in(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def post(client: Client, url: str, body: dict, org: str | None = None):
    headers = {"X-Org": org} if org else {}
    return client.post(url, data=body, content_type=JSON, headers=headers)


def new_user(email: str, name: str = "") -> User:
    return User.objects.create_user(email, "x" * 14, name=name)


def make_org(name: str, owner: User) -> Organisation:
    org_id = uuid.uuid4()
    with org_scope(org_id):
        org = Organisation.objects.create(id=org_id, name=name, slug=name.lower())
        Membership.objects.create(
            org_id=org.id, user=owner, role=Role.OWNER, status=MembershipStatus.ACTIVE
        )
    return org


def add_member(org: Organisation, user: User, role: str) -> Membership:
    with org_scope(org.id):
        return Membership.objects.create(
            org_id=org.id, user=user, role=role, status=MembershipStatus.ACTIVE
        )


# --- Creating an organisation -------------------------------------------------------------


def test_creating_an_organisation_makes_the_creator_its_owner():
    ada = new_user("ada@example.com")
    as_app_role()
    response = post(signed_in(ada), "/api/orgs/", {"name": "Acme Testing"})
    assert response.status_code == 201
    body = response.json()
    assert body["slug"] == "acme-testing" and body["name"] == "Acme Testing"

    me = signed_in(ada).get("/api/me/").json()
    assert [(m["organisation"]["slug"], m["role"], m["status"]) for m in me["memberships"]] == [
        ("acme-testing", "owner", "active")
    ]
    with org_scope(body["id"]):
        event = AuditEvent.objects.get(action="organisation.created")
    assert event.actor_id == ada.id and event.after["slug"] == "acme-testing"


def test_anonymous_users_cannot_create_organisations():
    as_app_role()
    assert post(Client(), "/api/orgs/", {"name": "Nope"}).status_code in (401, 403)


def test_an_address_that_is_taken_gets_a_suffix_when_it_was_not_chosen():
    make_org("Taken", new_user("first@example.com"))
    ada = new_user("ada2@example.com")
    as_app_role()
    response = post(signed_in(ada), "/api/orgs/", {"name": "Taken"})
    assert response.status_code == 201
    assert response.json()["slug"].startswith("taken-") and response.json()["slug"] != "taken"


def test_a_chosen_address_that_is_taken_is_refused():
    make_org("Chosen", new_user("first2@example.com"))
    ada = new_user("ada3@example.com")
    as_app_role()
    response = post(signed_in(ada), "/api/orgs/", {"name": "Another", "slug": "chosen"})
    assert response.status_code == 400


@pytest.mark.parametrize("slug", ["admin", "API", "a", "-bad", "has space", "x" * 41])
def test_reserved_or_malformed_addresses_are_refused(slug):
    ada = new_user("ada4@example.com")
    as_app_role()
    assert post(signed_in(ada), "/api/orgs/", {"name": "Z Org", "slug": slug}).status_code == 400


# --- Invitations --------------------------------------------------------------------------


def invite(owner_client: Client, org: Organisation, email: str, role: str = "qa_engineer"):
    return post(owner_client, "/api/invites/", {"email": email, "role": role}, org.slug)


def token_from_outbox(index: int = -1) -> str:
    match = re.search(r"/invite/([\w-]+)", str(mail.outbox[index].body))
    assert match, "no invitation link in the email"
    return match.group(1)


@pytest.fixture
def team(django_capture_on_commit_callbacks):
    owner = new_user("owner@example.com", "Olu Owner")
    org = make_org("Team", owner)
    invitee = new_user("newbie@example.com", "Nia")
    return org, owner, invitee, django_capture_on_commit_callbacks


def test_invite_then_accept_joins_with_the_role_the_inviter_chose(team):
    org, owner, invitee, capture = team
    as_app_role()
    with capture(execute=True):
        response = invite(signed_in(owner), org, "Newbie@Example.com", "qa_lead")
    assert response.status_code == 201
    assert "token" not in response.content.decode()  # the token goes only to the invitee's inbox

    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["newbie@example.com"]
    assert "Team" in mail.outbox[0].subject

    accepted = post(signed_in(invitee), "/api/invites/accept/", {"token": token_from_outbox()})
    assert accepted.status_code == 200 and accepted.json()["slug"] == "team"

    with org_scope(org.id):
        membership = Membership.objects.get(user=invitee)
        assert (membership.role, membership.status) == ("qa_lead", "active")
        assert set(AuditEvent.objects.values_list("action", flat=True)) >= {
            "member.invited",
            "member.joined",
        }
    # And they can now name the organisation.
    body = signed_in(invitee).get("/api/org/", headers={"X-Org": "team"}).json()
    assert body["role"] == "qa_lead"


def test_a_token_works_once(team):
    org, owner, invitee, capture = team
    as_app_role()
    with capture(execute=True):
        invite(signed_in(owner), org, invitee.email)
    token = token_from_outbox()
    assert post(signed_in(invitee), "/api/invites/accept/", {"token": token}).status_code == 200
    assert post(signed_in(invitee), "/api/invites/accept/", {"token": token}).status_code == 400


def test_the_token_is_stored_only_as_a_hash(team):
    org, owner, invitee, capture = team
    as_app_role()
    with capture(execute=True):
        invite(signed_in(owner), org, invitee.email)
    token = token_from_outbox()
    with org_scope(org.id):
        stored = Invitation.objects.get().token_hash
    assert token not in stored and len(stored) == 64


def test_someone_else_cannot_use_the_invitation(team):
    org, owner, invitee, capture = team
    mallory = new_user("mallory@example.com")
    as_app_role()
    with capture(execute=True):
        invite(signed_in(owner), org, invitee.email)
    stolen = post(signed_in(mallory), "/api/invites/accept/", {"token": token_from_outbox()})
    assert stolen.status_code == 400
    assert not Membership.all_objects.filter(user=mallory).exists()


def test_every_failure_to_accept_looks_the_same(team):
    org, owner, invitee, capture = team
    mallory = new_user("mallory2@example.com")
    as_app_role()
    with capture(execute=True):
        invite(signed_in(owner), org, invitee.email)
    good = token_from_outbox()
    answers = {
        post(signed_in(invitee), "/api/invites/accept/", {"token": "not-a-real-token"}).content,
        post(signed_in(mallory), "/api/invites/accept/", {"token": good}).content,
    }
    assert len(answers) == 1


def test_an_expired_invitation_cannot_be_accepted(team):
    org, owner, invitee, capture = team
    as_app_role()
    with capture(execute=True):
        invite(signed_in(owner), org, invitee.email)
    with org_scope(org.id):
        # The audit-style trigger covers only the audit table, so expiry can be rewound here.
        Invitation.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
    answer = post(signed_in(invitee), "/api/invites/accept/", {"token": token_from_outbox()})
    assert answer.status_code == 400


def test_inviting_again_replaces_the_earlier_invitation(team):
    org, owner, invitee, capture = team
    as_app_role()
    with capture(execute=True):
        invite(signed_in(owner), org, invitee.email)
        invite(signed_in(owner), org, invitee.email, "viewer")
    first, second = token_from_outbox(0), token_from_outbox(1)
    assert post(signed_in(invitee), "/api/invites/accept/", {"token": first}).status_code == 400
    assert post(signed_in(invitee), "/api/invites/accept/", {"token": second}).status_code == 200
    with org_scope(org.id):
        assert Membership.objects.get(user=invitee).role == "viewer"


def test_an_admin_cannot_invite_an_owner_but_an_owner_can(team):
    org, owner, invitee, capture = team
    admin = new_user("admin@example.com")
    add_member(org, admin, Role.ADMIN)
    as_app_role()
    with capture(execute=True):
        assert invite(signed_in(admin), org, invitee.email, "owner").status_code == 403
        assert invite(signed_in(owner), org, invitee.email, "owner").status_code == 201
        assert invite(signed_in(admin), org, invitee.email, "admin").status_code == 201


def test_existing_members_cannot_be_invited_again(team):
    org, owner, _, _ = team
    as_app_role()
    assert invite(signed_in(owner), org, owner.email).status_code == 400


def test_a_viewer_cannot_invite(team):
    org, _, invitee, _ = team
    add_member(org, invitee, Role.VIEWER)
    as_app_role()
    assert invite(signed_in(invitee), org, "someone@example.com").status_code == 403


def test_holding_a_token_reveals_only_that_invitation(team):
    """The invite-hash scope lets a token holder read their invitation, and nothing else."""
    org, owner, invitee, capture = team
    other = new_user("other-invitee@example.com")
    as_app_role()
    with capture(execute=True):
        invite(signed_in(owner), org, invitee.email)
        invite(signed_in(owner), org, other.email)
    from apps.core.services import hash_token

    with scoped(None, invitee.pk, hash_token(token_from_outbox(0))):
        assert list(Invitation.objects.values_list("email", flat=True)) == [invitee.email]
    set_scope(None, invitee.pk)
    assert Invitation.objects.count() == 0


# --- Members ------------------------------------------------------------------------------


def test_members_lists_the_organisations_people(team):
    org, owner, invitee, _ = team
    add_member(org, invitee, Role.DEVELOPER)
    as_app_role()
    rows = signed_in(owner).get("/api/members/", headers={"X-Org": "team"}).json()
    assert [(r["email"], r["role"]) for r in rows] == [
        ("owner@example.com", "owner"),
        ("newbie@example.com", "developer"),
    ]


def test_members_do_not_include_other_organisations_people(team):
    org, owner, _, _ = team
    make_org("Elsewhere", new_user("elsewhere@example.com"))
    as_app_role()
    rows = signed_in(owner).get("/api/members/", headers={"X-Org": "team"}).json()
    assert [r["email"] for r in rows] == ["owner@example.com"]


# --- Projects -----------------------------------------------------------------------------


def create_project(client: Client, org: Organisation, **body):
    body = {"name": "Hub", "key": "hube", **body}
    return post(client, "/api/projects/", body, org.slug)


def test_an_admin_creates_a_project_with_members(team):
    org, owner, invitee, _ = team
    add_member(org, invitee, Role.QA_ENGINEER)
    as_app_role()
    response = create_project(
        signed_in(owner), org, client_name="Hube Ltd", member_ids=[str(invitee.id)]
    )
    assert response.status_code == 201
    assert response.json()["key"] == "HUBE" and response.json()["client_name"] == "Hube Ltd"
    with org_scope(org.id):
        assert ProjectMember.objects.filter(user=invitee).count() == 1
        assert AuditEvent.objects.filter(action="project.created").count() == 1


def test_project_keys_are_unique_within_an_organisation(team):
    org, owner, _, _ = team
    as_app_role()
    assert create_project(signed_in(owner), org).status_code == 201
    assert create_project(signed_in(owner), org, key="HUBE").status_code == 400
    assert create_project(signed_in(owner), org, key="x").status_code == 400
    assert create_project(signed_in(owner), org, key="TOOLONGKEY").status_code == 400


def test_two_organisations_can_use_the_same_project_key(team):
    org, owner, _, _ = team
    other_owner = new_user("other-owner@example.com")
    other = make_org("Other", other_owner)
    as_app_role()
    assert create_project(signed_in(owner), org).status_code == 201
    assert create_project(signed_in(other_owner), other).status_code == 201


def test_project_members_must_belong_to_the_organisation(team):
    org, owner, _, _ = team
    outsider = new_user("outsider@example.com")
    as_app_role()
    response = create_project(signed_in(owner), org, member_ids=[str(outsider.id)])
    assert response.status_code == 400
    with org_scope(org.id):
        assert not Project.objects.exists()


def test_a_qa_engineer_cannot_create_a_project(team):
    org, _, invitee, _ = team
    add_member(org, invitee, Role.QA_ENGINEER)
    as_app_role()
    assert create_project(signed_in(invitee), org).status_code == 403


def test_members_only_see_projects_they_belong_to(team):
    org, owner, invitee, _ = team
    add_member(org, invitee, Role.QA_ENGINEER)
    as_app_role()
    owners = signed_in(owner)
    create_project(owners, org, name="Mine", key="MINE", member_ids=[str(invitee.id)])
    create_project(owners, org, name="Theirs", key="THEIRS")

    engineer = signed_in(invitee)
    seen = [p["key"] for p in engineer.get("/api/projects/", headers={"X-Org": "team"}).json()]
    assert seen == ["MINE"]
    assert engineer.get("/api/projects/mine/", headers={"X-Org": "team"}).status_code == 200
    assert engineer.get("/api/projects/theirs/", headers={"X-Org": "team"}).status_code == 404

    everything = [p["key"] for p in owners.get("/api/projects/", headers={"X-Org": "team"}).json()]
    assert everything == ["MINE", "THEIRS"]


def test_another_organisations_project_is_not_found(team):
    org, owner, _, _ = team
    other_owner = new_user("other-owner2@example.com")
    other = make_org("Rival", other_owner)
    as_app_role()
    create_project(signed_in(other_owner), other, name="Secret", key="SECRET")
    mine = signed_in(owner)
    assert mine.get("/api/projects/secret/", headers={"X-Org": "team"}).status_code == 404
    assert mine.get("/api/projects/secret/", headers={"X-Org": "rival"}).status_code == 404
