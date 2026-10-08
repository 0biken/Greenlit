"""Cross-tenant isolation suite (M1-15, SEC §5, DATA §8 rule 7, AI-04).

Two organisations are seeded with sample data in every tenant table. Then, as a user of
Alpha, the suite checks the database, every API endpoint and every method against Bravo's data.
Endpoints and tables are discovered, not listed, so a new endpoint or tenant table is covered
automatically (a new table with no sample data fails the seed check below).

When search, file routes and exports exist, add them to the discovery here.
"""

import pytest
from django.db import connection
from django.test import Client

from apps.core import services
from apps.core.models import (
    CounterKind,
    Job,
    JobState,
    Membership,
    MembershipStatus,
    Organisation,
    ProjectMember,
    Role,
    User,
)
from apps.core.numbering import next_number
from apps.core.tenancy import org_scope, set_scope
from tests.support import api_endpoints, declared, methods_of, url_for

pytestmark = pytest.mark.django_db

# Everything that belongs to Bravo carries one of these, so a leak is easy to spot in a response.
BRAVO_MARKERS = ["BRAVO-CONFIDENTIAL", "bravo-secret.example", "Bravo Spy", "SECRTB"]


class World:
    """Alpha and Bravo, each with an owner, an engineer, projects, an invitation and audit rows."""


@pytest.fixture
def world():
    w = World()
    for tag, display in (("alpha", "Alpha"), ("bravo", "BRAVO-CONFIDENTIAL")):
        domain = "bravo-secret.example" if tag == "bravo" else "alpha-iso.example"
        owner = User.objects.create_user(
            f"owner@{domain}", "x" * 14, name="Bravo Spy" if tag == "bravo" else "Alpha Owner"
        )
        engineer = User.objects.create_user(f"engineer@{domain}", "x" * 14, name=f"{tag} engineer")
        org = services.create_organisation(owner, f"{display} Org", f"{tag}-iso")
        with org_scope(org.id, owner.pk):
            Membership.objects.create(
                org_id=org.id, user=engineer, role=Role.QA_ENGINEER, status=MembershipStatus.ACTIVE
            )
            owner_membership = Membership.objects.get(user=owner)
            shared = services.create_project(
                owner_membership, f"{display} shared project", "SHARED", member_ids=[engineer.pk]
            )
            private_key = "SECRTB" if tag == "bravo" else "ALPHAP"
            services.create_project(owner_membership, f"{display} private", private_key)
            services.invite_member(owner_membership, org, f"invitee@{domain}", Role.VIEWER.value)
            next_number(shared.pk, org.pk, CounterKind.DEFECT)
            assert ProjectMember.objects.filter(user=engineer).exists()
            job = Job.objects.create(org_id=org.id, kind="sample", state=JobState.DEAD)
        setattr(w, tag, org)
        setattr(w, f"{tag}_job", job)
        setattr(w, f"{tag}_owner", owner)
        setattr(w, f"{tag}_engineer", engineer)
    return w


def tenant_tables() -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT c.relname FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r'
              AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                          AND a.attname = 'org_id' AND NOT a.attisdropped)
            ORDER BY 1
            """
        )
        return [row[0] for row in cursor.fetchall()]


def as_app_role():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")


def client_for(user: User) -> Client:
    client = Client()
    client.force_login(user)
    return client


# --- The database ---------------------------------------------------------------------------


def test_every_tenant_table_has_sample_data_for_both_organisations(world):
    """A new tenant table must be added to the seed above, or this suite proves nothing for it."""
    empty = []
    for table in tenant_tables():
        for org in (world.alpha, world.bravo):
            with org_scope(org.id):
                with connection.cursor() as cursor:
                    cursor.execute(f'SELECT count(*) FROM "{table}" WHERE org_id = %s', [org.id])
                    if cursor.fetchone()[0] == 0:
                        empty.append(f"{table} has no rows for {org.slug}")
    assert empty == [], "Seed these tables in the `world` fixture: " + "; ".join(empty)


def test_the_database_hides_bravos_rows_from_alpha_in_every_tenant_table(world):
    as_app_role()
    set_scope(world.alpha.id, world.alpha_owner.pk)
    leaks = []
    for table in tenant_tables():
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM "{table}" WHERE org_id <> %s', [world.alpha.id])
            if cursor.fetchone()[0]:
                leaks.append(table)
            cursor.execute(f'SELECT count(*) FROM "{table}"')
            assert cursor.fetchone()[0] > 0, f"{table} shows Alpha nothing: the check is vacuous"
    assert leaks == []


def test_without_any_scope_a_tenant_table_cannot_be_read_at_all(world):
    as_app_role()
    set_scope(None, None)
    from django.db import DatabaseError, transaction

    unscoped_ok = []
    for table in tenant_tables():
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute(f'SELECT count(*) FROM "{table}"')
                rows = cursor.fetchone()[0]
                # Tables whose policy also admits "my own rows" or "my token" return nothing
                # instead of failing; they must still return zero rows.
                if rows:
                    unscoped_ok.append(table)
        except DatabaseError:
            pass
    assert unscoped_ok == []


# --- The API --------------------------------------------------------------------------------


def test_naming_bravo_as_alpha_is_not_found_on_every_endpoint_and_method(world):
    as_app_role()
    client = client_for(world.alpha_owner)
    checked = 0
    for route, view_cls in api_endpoints():
        for method in methods_of(view_cls):
            response = getattr(client, method)(
                url_for(route),
                data={},
                content_type="application/json",
                headers={"X-Org": "bravo-iso"},
            )
            assert response.status_code == 404, (
                f"{method.upper()} {route} answered {response.status_code} to a request "
                "naming another tenant's organisation"
            )
            checked += 1
    assert checked >= 10


def test_a_users_own_organisation_list_never_includes_bravo(world):
    as_app_role()
    body = client_for(world.alpha_owner).get("/api/me/").json()
    assert [m["organisation"]["slug"] for m in body["memberships"]] == ["alpha-iso"]


def test_no_alpha_response_contains_any_of_bravos_data(world):
    as_app_role()
    seen_ok = 0
    for user in (world.alpha_owner, world.alpha_engineer):
        client = client_for(user)
        for route, view_cls in api_endpoints():
            if "get" not in methods_of(view_cls):
                continue
            response = client.get(
                url_for(route, {"key": "SHARED", "job_id": str(world.alpha_job.id)}),
                headers={"X-Org": "alpha-iso"},
            )
            text = response.content.decode(errors="replace")
            for marker in BRAVO_MARKERS:
                assert marker not in text, f"GET {route} as {user.email} leaked {marker!r}"
            seen_ok += response.status_code == 200
    assert seen_ok >= 8, "too few successful calls: the leak scan is not looking at real data"


def test_bravos_identifiers_are_not_found_under_alpha(world):
    as_app_role()
    for user in (world.alpha_owner, world.alpha_engineer):
        client = client_for(user)
        for route, view_cls in api_endpoints():
            if "<" not in route or "get" not in methods_of(view_cls):
                continue
            response = client.get(
                url_for(route, {"key": "SECRTB", "job_id": str(world.bravo_job.id)}),
                headers={"X-Org": "alpha-iso"},
            )
            assert response.status_code == 404, f"GET {route} with Bravo's key as {user.email}"


def test_the_same_project_key_in_two_organisations_resolves_to_your_own(world):
    as_app_role()
    mine = client_for(world.alpha_owner).get(
        "/api/projects/shared/", headers={"X-Org": "alpha-iso"}
    )
    theirs = client_for(world.bravo_owner).get(
        "/api/projects/shared/", headers={"X-Org": "bravo-iso"}
    )
    assert mine.json()["name"] == "Alpha shared project"
    assert theirs.json()["name"] == "BRAVO-CONFIDENTIAL shared project"


def test_a_bravo_user_cannot_read_alpha_data_either(world):
    """The isolation is symmetric."""
    as_app_role()
    client = client_for(world.bravo_owner)
    assert client.get("/api/projects/alphap/", headers={"X-Org": "alpha-iso"}).status_code == 404
    assert client.get("/api/members/", headers={"X-Org": "alpha-iso"}).status_code == 404


def test_every_endpoint_has_a_declared_policy_so_it_is_part_of_this_suite(world):
    undeclared = [route for route, cls in api_endpoints() if cls is None or declared(cls) is None]
    assert undeclared == []


def test_alphas_organisation_record_is_the_only_one_visible(world):
    as_app_role()
    set_scope(world.alpha.id, world.alpha_owner.pk)
    assert list(Organisation.objects.values_list("slug", flat=True)) == ["alpha-iso"]
