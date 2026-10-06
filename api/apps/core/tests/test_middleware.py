"""The tenancy middleware, tested end to end as the restricted app role (M1-04)."""

import uuid

import pytest
from django.db import connection
from django.test import Client

from apps.core.models import Membership, MembershipStatus, Organisation, Project, Role, User
from apps.core.tenancy import get_scope, org_scope

pytestmark = pytest.mark.django_db


def make_org(name: str) -> Organisation:
    org_id = uuid.uuid4()
    with org_scope(org_id):
        org = Organisation.objects.create(id=org_id, name=name, slug=name.lower())
        Project.objects.create(org_id=org.id, name=f"{name} app", key=name[:3].upper())
    return org


def join(org: Organisation, user: User, role=Role.QA_ENGINEER, status=MembershipStatus.ACTIVE):
    with org_scope(org.id):
        Membership.objects.create(org_id=org.id, user=user, role=role, status=status)


@pytest.fixture
def world():
    alpha, beta = make_org("Alpha"), make_org("Beta")
    ada = User.objects.create_user("ada@example.com", "x" * 14, name="Ada")
    bob = User.objects.create_user("bob@example.com", "x" * 14, name="Bob")
    join(alpha, ada, Role.QA_LEAD)
    join(beta, ada, Role.VIEWER)
    join(beta, bob, Role.OWNER)
    return alpha, beta, ada, bob


def as_app_role():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")


def client_for(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


def test_anonymous_request_is_refused_and_has_no_scope(world):
    as_app_role()
    response = Client().get("/api/me/")
    assert response.status_code in (401, 403)
    assert get_scope() == ("", "", "")


def test_me_lists_only_the_users_own_memberships_without_choosing_an_organisation(world):
    alpha, beta, ada, bob = world
    as_app_role()
    body = client_for(ada).get("/api/me/").json()
    assert body["email"] == "ada@example.com"
    roles = {m["organisation"]["slug"]: m["role"] for m in body["memberships"]}
    assert roles == {"alpha": "qa_lead", "beta": "viewer"}


def test_naming_an_organisation_you_belong_to_sets_the_scope(world):
    alpha, _, ada, _ = world
    as_app_role()
    response = client_for(ada).get("/api/org/", headers={"X-Org": "alpha"})
    assert response.status_code == 200
    assert response.json() == {
        "id": str(alpha.id),
        "slug": "alpha",
        "name": "Alpha",
        "role": "qa_lead",
    }


def test_role_is_the_one_in_the_named_organisation(world):
    _, _, ada, _ = world
    as_app_role()
    body = client_for(ada).get("/api/org/", headers={"X-Org": "beta"}).json()
    assert body["role"] == "viewer"


def test_an_organisation_you_do_not_belong_to_looks_like_one_that_does_not_exist(world):
    alpha, _, _, bob = world
    as_app_role()
    client = client_for(bob)
    other_tenant = client.get("/api/org/", headers={"X-Org": "alpha"})
    nonexistent = client.get("/api/org/", headers={"X-Org": "no-such-org"})
    assert other_tenant.status_code == nonexistent.status_code == 404
    assert other_tenant.content == nonexistent.content


@pytest.mark.parametrize("status", [MembershipStatus.INVITED, MembershipStatus.REMOVED])
def test_only_active_memberships_count(world, status):
    alpha, _, _, _ = world
    carol = User.objects.create_user("carol@example.com", "x" * 14)
    join(alpha, carol, status=status)
    as_app_role()
    assert client_for(carol).get("/api/org/", headers={"X-Org": "alpha"}).status_code == 404


def test_tenant_endpoints_answer_not_found_when_no_organisation_is_named(world):
    _, _, ada, _ = world
    as_app_role()
    assert client_for(ada).get("/api/org/").status_code == 404


def test_scope_does_not_outlive_the_request(world):
    _, _, ada, _ = world
    as_app_role()
    before = get_scope()
    client_for(ada).get("/api/org/", headers={"X-Org": "alpha"})
    assert get_scope() == before


def test_a_user_cannot_see_other_users_memberships(world):
    _, _, ada, bob = world
    as_app_role()
    memberships = client_for(bob).get("/api/me/").json()["memberships"]
    assert [m["organisation"]["slug"] for m in memberships] == ["beta"]
