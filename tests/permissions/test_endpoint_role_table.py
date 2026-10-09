"""Every API endpoint × every role (M1-11, SEC §4).

The build fails if an endpoint has no declared policy, so a new endpoint cannot ship with
DRF's silent default. Endpoints with a role-gated method other than GET need a body sample in
SAMPLES, and routes with URL parameters need an entry in PARAMS, so they are exercised too.
"""

import itertools
import uuid

import pytest
from django.db import connection
from django.test import Client

from apps.core.models import (
    Job,
    JobState,
    Membership,
    MembershipStatus,
    Organisation,
    Project,
    ProjectMember,
    Role,
    User,
)
from apps.core.policy import can
from apps.core.tenancy import org_scope
from tests.support import HANDLED, api_endpoints, declared, stored_file, url_for

pytestmark = pytest.mark.django_db

ROLES = [r.value for r in Role]
_counter = itertools.count(1)


def _letters(n: int) -> str:
    out = ""
    for _ in range(3):
        out, n = out + chr(ord("A") + n % 26), n // 26
    return out


# Request bodies for role-gated methods other than GET. Each call must produce fresh values.
SAMPLES = {
    ("api/invites/", "post"): lambda: {
        "email": f"invitee{next(_counter)}@example.com",
        "role": "viewer",
    },
    ("api/projects/", "post"): lambda: {"name": "Sample", "key": _letters(next(_counter))},
    ("api/jobs/<uuid:job_id>/rerun/", "post"): lambda: {},
    ("api/projects/<str:key>/files/", "post"): lambda: {
        "kind": "evidence",
        "name": "shot.png",
        "size": 100,
    },
    ("api/files/<uuid:file_id>/complete/", "post"): lambda: {},
}


def role_gated_calls():
    """(route, view class, method, action) for every role-gated method of every endpoint."""
    for route, view_cls in api_endpoints():
        actions = declared(view_cls) if view_cls else None
        if not isinstance(actions, dict):
            continue
        for method in HANDLED:
            if hasattr(view_cls, method):
                action = actions.get(method.upper())
                if action is not None:
                    yield route, view_cls, method, action


def body_for(route: str, method: str):
    if method == "get":
        return None
    sample = SAMPLES.get((route, method))
    assert sample is not None, (
        f"{method.upper()} {route} is role-gated; add a body sample to SAMPLES in this table"
    )
    return sample()


def call(client: Client, route: str, method: str, org_slug: str | None, params=None):
    kwargs = {"headers": {"X-Org": org_slug}} if org_slug else {}
    body = body_for(route, method)
    if body is not None:
        kwargs.update(data=body, content_type="application/json")
    return getattr(client, method)(url_for(route, params), **kwargs)


def _org_with_a_member_of_each_role():
    org_id = uuid.uuid4()
    users = {}
    with org_scope(org_id):
        org = Organisation.objects.create(id=org_id, name="Table", slug="table")
        project = Project.objects.create(org_id=org.id, name="Sample", key="SAMPLE")
        for role in ROLES:
            user = User.objects.create_user(f"{role}@table.example", "x" * 14)
            Membership.objects.create(
                org_id=org.id, user=user, role=role, status=MembershipStatus.ACTIVE
            )
            # Everyone is on the sample project, so the matrix answer is not hidden by 404s.
            ProjectMember.objects.create(org_id=org.id, project=project, user=user)
            users[role] = user
        # A job that gave up, so re-running it is a valid request.
        job = Job.objects.create(org_id=org.id, kind="sample", state=JobState.DEAD)
        # An available file, so downloading it and completing it (a no-op) are valid requests.
        upload = stored_file(org, project, "evidence.png")
    return org, users, {"job_id": str(job.id), "file_id": str(upload.id)}


def _as_app_role():
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL ROLE greenlit_app")


def test_the_table_is_not_empty():
    assert len(list(api_endpoints())) >= 10
    assert len(list(role_gated_calls())) >= 5


@pytest.mark.parametrize("route,view_cls", list(api_endpoints()), ids=lambda v: str(v))
def test_every_endpoint_declares_a_policy(route, view_cls):
    assert view_cls is not None, f"{route}: not a DRF view; add a policy and a row to this table"
    assert declared(view_cls) is not None, (
        f"{route} declares no policy. Use requires(Action.X), AuthenticatedOnly or Public "
        "from apps.core.policy."
    )


@pytest.mark.parametrize("route,view_cls,method,action", list(role_gated_calls()), ids=str)
def test_each_role_gets_the_matrix_answer(route, view_cls, method, action):
    org, users, params = _org_with_a_member_of_each_role()
    _as_app_role()
    for role, user in users.items():
        client = Client()
        client.force_login(user)
        response = call(client, route, method, org.slug, params)
        if can(role, action):
            assert response.status_code < 400, (
                f"{method.upper()} {route} as {role}: {response.status_code} {response.content!r}"
            )
        else:
            assert response.status_code == 403, (
                f"{method.upper()} {route} as {role}: {response.status_code}"
            )


@pytest.mark.parametrize("route,view_cls,method,action", list(role_gated_calls()), ids=str)
def test_without_an_organisation_or_membership_it_is_not_found(route, view_cls, method, action):
    org, _, params = _org_with_a_member_of_each_role()
    outsider = User.objects.create_user("outsider@table.example", "x" * 14)
    _as_app_role()
    client = Client()
    client.force_login(outsider)
    assert call(client, route, method, None, params).status_code == 404
    assert call(client, route, method, org.slug, params).status_code == 404


@pytest.mark.parametrize("route,view_cls", list(api_endpoints()), ids=lambda v: str(v))
def test_anonymous_callers_only_reach_public_endpoints(route, view_cls):
    response = Client().get(url_for(route))
    if declared(view_cls) == "public":
        assert response.status_code == 200
    else:
        assert response.status_code in (401, 403), f"{route} answered {response.status_code}"
