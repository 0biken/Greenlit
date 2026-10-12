"""A small organisation for behaviour tests of the requirement-to-sign-off chain.

One person per role, one project everyone is on, and builders that go through the real
services, so every rule applies. Each builder sets the organisation scope itself; wrap reads
and direct service calls in `with lab.scope():`.
"""

import uuid
from datetime import timedelta

from django.test import Client
from django.utils import timezone

from apps.core.choices import Priority
from apps.core.models import (
    Membership,
    MembershipStatus,
    Organisation,
    Project,
    ProjectMember,
    Role,
    User,
)
from apps.core.tenancy import org_scope
from apps.defects import status
from apps.defects.models import Defect
from apps.plans import services as plans
from apps.requirements.services import create_requirement
from apps.runs import services as runs
from apps.runs.models import CaseResult
from tests.support import stored_file

JSON = "application/json"


class Lab:
    def __init__(self, slug: str = "lab", key: str = "LAB"):
        self.id = uuid.uuid4()
        self.slug = slug
        with self.scope():
            self.org = Organisation.objects.create(id=self.id, name=slug.title(), slug=slug)
            self.project = Project.objects.create(org_id=self.id, name="Checkout", key=key)
        self.users = {role: self.add(role) for role in Role.values}
        self.owner = self.users[Role.OWNER]
        self.lead = self.users[Role.QA_LEAD]
        self.tester = self.users[Role.QA_ENGINEER]
        self.developer = self.users[Role.DEVELOPER]
        self.viewer = self.users[Role.VIEWER]

    def scope(self):
        return org_scope(self.id)

    def add(self, role: str) -> User:
        user = User.objects.create_user(
            f"{role}-{uuid.uuid4().hex[:6]}@lab.test", "x" * 14, name=role
        )
        with self.scope():
            Membership.objects.create(
                org_id=self.id, user=user, role=role, status=MembershipStatus.ACTIVE
            )
            ProjectMember.objects.create(org_id=self.id, project=self.project, user=user)
        return user

    def membership(self, user: User) -> Membership:
        with self.scope():
            return Membership.objects.select_related("user").get(user=user)

    # --- builders ----------------------------------------------------------------------------

    def requirement(self, title="Pay by card", priority=Priority.MEDIUM, **kw):
        with self.scope():
            return create_requirement(
                self.project, self.lead, title=title, text=title, priority=priority, **kw
            )

    def plan(self, title="Checkout", cases=(), approve=True):
        """`cases` is a list of (title, [requirements]). Returns (plan, version, revisions)."""
        with self.scope():
            plan = plans.create_plan(self.project, self.lead, title=title)
            revisions = [
                plans.add_case(
                    plans.draft_of(plan),
                    self.lead,
                    title=t,
                    steps=["Do it"],
                    expected="It works.",
                    requirements=reqs,
                )
                for t, reqs in cases
            ]
            version = (
                plans.approve(plans.draft_of(plan), self.lead) if approve else plans.draft_of(plan)
            )
        return plan, version, revisions

    def release(self, name="1.0", due_in_days: int | None = 3):
        with self.scope():
            due = (
                timezone.now().date() + timedelta(days=due_in_days)
                if due_in_days is not None
                else None
            )
            return runs.create_release(self.project, self.lead, name=name, target_date=due)

    def run(self, release, version, outcomes=()):
        """Start a run and record `outcomes` in case order. Returns (run, results)."""
        with self.scope():
            run = runs.start_run(release, version, self.tester, build="100", environment="staging")
            results = list(CaseResult.objects.filter(run=run).order_by("created_at"))
            for result, outcome in zip(results, outcomes, strict=False):
                runs.record_result(result, self.tester, outcome)
        return run, results

    def file(self, name="shot.png"):
        with self.scope():
            return stored_file(self.org, self.project, name)

    def defect(
        self,
        title="Payment times out",
        *,
        severity=Priority.HIGH,
        owner=None,
        release=None,
        result=None,
    ):
        with self.scope():
            return status.create_defect(
                self.project,
                self.tester,
                title=title,
                severity=severity,
                owner=owner or self.tester,
                release=release,
                found_in_result=result,
            )

    def set(self, defect, tracker_status: str, actor=None) -> Defect:
        with self.scope():
            return status.set_tracker_status(defect, actor or self.developer, tracker_status)

    def retest(self, defect, outcome="passed", actor=None, files=None) -> Defect:
        with self.scope():
            ids = [f.pk for f in files] if files is not None else [self.file().pk]
            status.record_retest(
                defect, actor or self.tester, outcome=outcome, evidence_file_ids=ids
            )
            return Defect.objects.get(pk=defect.pk)

    def backdate(self, obj, **fields):
        """Move timestamps into the past (tests of ages and thresholds)."""
        with self.scope():
            type(obj).all_objects.filter(pk=obj.pk).update(**fields)
            obj.refresh_from_db()
        return obj

    # --- HTTP -------------------------------------------------------------------------------

    def call(self, user: User, method: str, path: str, body=None):
        client = Client()
        client.force_login(user)
        kwargs: dict = {"headers": {"X-Org": self.slug}}
        if body is not None:
            kwargs.update(data=body, content_type=JSON)
        return getattr(client, method)(path, **kwargs)


def days_ago(n: float):
    return timezone.now() - timedelta(days=n)
