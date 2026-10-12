"""Every API endpoint × every role (M1-11, SEC §4).

The build fails if an endpoint has no declared policy, so a new endpoint cannot ship with
DRF's silent default. Endpoints with a role-gated method other than GET need a body sample in
SAMPLES, and routes with URL parameters need an entry in PARAMS, so they are exercised too.
"""

import hashlib
import itertools
import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone

from apps.core.models import (
    Invitation,
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
from apps.defects.status import create_defect, set_tracker_status
from apps.plans import services as plans
from apps.requirements.services import create_requirement
from apps.runs.models import CaseResult
from apps.runs.services import create_release, start_run
from tests.support import HANDLED, api_endpoints, declared, stored_file, url_for

pytestmark = pytest.mark.django_db

ROLES = [r.value for r in Role]
_counter = itertools.count(1)


def _letters(n: int) -> str:
    out = ""
    for _ in range(3):
        out, n = out + chr(ord("A") + n % 26), n // 26
    return out


# Request bodies for role-gated methods other than GET. Each is called with the fixture's
# context and must produce fresh values, because every role makes the call in turn.
SAMPLES = {
    ("api/invites/", "post"): lambda ctx: {
        "email": f"invitee{next(_counter)}@example.com",
        "role": "viewer",
    },
    ("api/projects/", "post"): lambda ctx: {"name": "Sample", "key": _letters(next(_counter))},
    ("api/jobs/<uuid:job_id>/rerun/", "post"): lambda ctx: {},
    ("api/projects/<str:key>/files/", "post"): lambda ctx: {
        "kind": "evidence",
        "name": "shot.png",
        "size": 100,
    },
    ("api/files/<uuid:file_id>/complete/", "post"): lambda ctx: {},
    ("api/members/<uuid:user_id>/", "patch"): lambda ctx: {"role": "developer"},
    ("api/members/<uuid:user_id>/", "delete"): lambda ctx: {},
    ("api/invites/<uuid:invite_id>/", "delete"): lambda ctx: {},
    ("api/projects/<str:key>/", "patch"): lambda ctx: {"client_name": "Client X"},
    ("api/projects/<str:key>/members/", "post"): lambda ctx: {"user_id": ctx["fresh_member"]()},
    ("api/projects/<str:key>/members/<uuid:user_id>/", "delete"): lambda ctx: {},
    ("api/inbox/<str:item_id>/snooze/", "post"): lambda ctx: {
        "reason": "Waiting for staging",
        "until": (timezone.now() + timedelta(days=2)).isoformat(),
    },
    ("api/inbox/<str:item_id>/unsnooze/", "post"): lambda ctx: {},
    ("api/projects/<str:key>/releases/<str:version>/sign-off/", "post"): lambda ctx: {"reason": ""},
    ("api/projects/<str:key>/defects/<str:defect_id>/fixed/", "post"): lambda ctx: {},
    ("api/projects/<str:key>/defects/", "post"): lambda ctx: {"title": "Sample defect"},
    ("api/projects/<str:key>/releases/", "post"): lambda ctx: {"version": f"8.{next(_counter)}"},
    ("api/projects/<str:key>/releases/<str:version>/cancel/", "post"): lambda ctx: {},
    ("api/projects/<str:key>/runs/", "post"): lambda ctx: {
        "plan": ctx["plan_no"],
        "release": ctx["open_release"],
    },
    ("api/projects/<str:key>/runs/<str:run_id>/complete/", "post"): lambda ctx: {},
    ("api/projects/<str:key>/runs/<str:run_id>/results/<uuid:result_id>/", "put"): lambda ctx: {
        "outcome": "passed"
    },
    (
        "api/projects/<str:key>/runs/<str:run_id>/results/<uuid:result_id>/evidence/",
        "post",
    ): lambda ctx: {"file_ids": [ctx["file_id"]]},
    ("api/projects/<str:key>/defects/<str:defect_id>/", "patch"): lambda ctx: {"title": "Renamed"},
    ("api/projects/<str:key>/defects/<str:defect_id>/status/", "post"): lambda ctx: {
        "status": "closed"
    },
    ("api/projects/<str:key>/defects/<str:defect_id>/decision/", "post"): lambda ctx: {
        "decision": "deferred",
        "reason": "Moved to the next release",
    },
    ("api/projects/<str:key>/defects/<str:defect_id>/retests/", "post"): lambda ctx: {
        "outcome": "passed",
        "evidence_file_ids": [ctx["file_id"]],
    },
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


def body_for(route: str, method: str, ctx: dict):
    if method == "get":
        return None
    sample = SAMPLES.get((route, method))
    assert sample is not None, (
        f"{method.upper()} {route} is role-gated; add a body sample to SAMPLES in this table"
    )
    return sample(ctx)


def call(client: Client, route: str, method: str, org_slug: str | None, ctx: dict):
    kwargs = {"headers": {"X-Org": org_slug}} if org_slug else {}
    body = body_for(route, method, ctx)
    # A parameter given as a function makes a fresh target for each call.
    params = {k: v() if callable(v) else v for k, v in ctx["params"].items()}
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
        requirement = create_requirement(project, None, title="Pay by card", text="Card payments.")
        # A published plan, an open release and a run on it, so the run routes have targets.
        plan = plans.create_plan(project, None, title="Sample plan")
        plans.add_case(
            plans.draft_of(plan), None, title="Pays by card", steps=["Pay"], expected="Paid."
        )
        version = plans.approve(plans.draft_of(plan), None)
        open_release = create_release(project, None, name="7.0")
        run = start_run(open_release, version, None)
        result = CaseResult.objects.get(run=run)
        fixer = User.objects.create_user("fixer@table.example", "x" * 14)
        Membership.objects.create(
            org_id=org.id, user=fixer, role=Role.DEVELOPER, status=MembershipStatus.ACTIVE
        )

    def fresh_release() -> str:
        """An empty open release, so signing it off is a valid request (it is Ready)."""
        with org_scope(org.id):
            return create_release(project, None, name=f"9.{next(_counter)}").name

    def fresh_fixed_defect() -> str:
        """A defect someone else marked fixed: setting it fixed again is a no-op, and any
        tester may retest it (the fixer-cannot-verify rule does not apply to them)."""
        with org_scope(org.id):
            defect = create_defect(project, None, title="Sample defect")
            set_tracker_status(defect, fixer, "fixed")
        return str(defect.display_no)

    def fresh_member() -> str:
        """A viewer on the sample project, for calls that change or remove someone."""
        with org_scope(org.id):
            user = User.objects.create_user(f"target{next(_counter)}@table.example", "x" * 14)
            Membership.objects.create(
                org_id=org.id, user=user, role=Role.VIEWER, status=MembershipStatus.ACTIVE
            )
            ProjectMember.objects.create(org_id=org.id, project=project, user=user)
        return str(user.id)

    def fresh_invitation() -> str:
        with org_scope(org.id):
            invitation = Invitation.objects.create(
                org_id=org.id,
                email=f"pending{next(_counter)}@table.example",
                role=Role.VIEWER,
                token_hash=hashlib.sha256(uuid.uuid4().bytes).hexdigest(),
                expires_at=timezone.now() + timedelta(days=1),
                invited_by=users[Role.OWNER.value],
            )
        return str(invitation.id)

    ctx = {
        "fresh_member": fresh_member,
        "file_id": str(upload.id),
        "plan_no": plan.display_no,
        "open_release": open_release.name,
        "params": {
            "run_id": str(run.display_no),
            "result_id": str(result.pk),
            "job_id": str(job.id),
            "file_id": str(upload.id),
            "user_id": fresh_member,
            "invite_id": fresh_invitation,
            "version": fresh_release,
            "defect_id": fresh_fixed_defect,
            "item_id": f"requirement.{requirement.pk}",
        },
    }
    return org, users, ctx


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
    org, users, ctx = _org_with_a_member_of_each_role()
    _as_app_role()
    for role, user in users.items():
        client = Client()
        client.force_login(user)
        response = call(client, route, method, org.slug, ctx)
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
    org, _, ctx = _org_with_a_member_of_each_role()
    outsider = User.objects.create_user("outsider@table.example", "x" * 14)
    _as_app_role()
    client = Client()
    client.force_login(outsider)
    assert call(client, route, method, None, ctx).status_code == 404
    assert call(client, route, method, org.slug, ctx).status_code == 404


@pytest.mark.parametrize("route,view_cls", list(api_endpoints()), ids=lambda v: str(v))
def test_anonymous_callers_only_reach_public_endpoints(route, view_cls):
    response = Client().get(url_for(route))
    if declared(view_cls) == "public":
        assert response.status_code == 200
    else:
        assert response.status_code in (401, 403), f"{route} answered {response.status_code}"
