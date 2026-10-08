import uuid

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(self, email: str, password: str | None = None, **extra):
        if not email:
            raise ValueError("An email address is required")
        user = self.model(email=self.normalize_email(email).lower(), **extra)
        user.set_password(password)  # type: ignore[attr-defined]
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra):
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    """Global account; not scoped to one organisation (DATA §3)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    name = models.CharField(max_length=200, blank=True)
    auth_provider = models.CharField(max_length=50, default="email")
    time_zone = models.CharField(max_length=64, default="UTC")  # digest time (G-03)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    USERNAME_FIELD = "email"
    objects = UserManager()


class TenantQuerySet(models.QuerySet):
    def delete(self):
        """Soft delete: records are never hard-deleted in normal use (DATA §1)."""
        return self.update(deleted_at=timezone.now())


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):  # type: ignore[misc]
    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class TenantModel(models.Model):
    """Base for every tenant-owned table (DATA §1).

    `org_id` is set from the request's organisation scope, never from client input.
    Row-level security keyed on `org_id` is added per table by the migration helper
    in `apps.core.rls` (M1-03).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_id = models.UUIDField(db_index=True)
    created_at = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey(
        "core.User", null=True, on_delete=models.PROTECT, related_name="+", editable=False
    )
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):  # type: ignore[override]
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at", "updated_at"])
        return 1, {self._meta.label: 1}


class Organisation(TenantModel):
    """Root of every tenant. `org_id` on its own row equals `id` (DATA §3)."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=60, unique=True)
    plan_tier = models.CharField(max_length=30, default="starter")
    ai_allowance = models.PositiveIntegerField(default=0)

    def save(self, *args, **kwargs):
        self.org_id = self.id
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Role(models.TextChoices):
    OWNER = "owner"
    ADMIN = "admin"
    QA_LEAD = "qa_lead"
    QA_ENGINEER = "qa_engineer"
    DEVELOPER = "developer"
    VIEWER = "viewer"


class MembershipStatus(models.TextChoices):
    INVITED = "invited"
    ACTIVE = "active"
    REMOVED = "removed"


class Membership(TenantModel):
    """One row per user per organisation (DATA §3)."""

    user = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices)
    status = models.CharField(
        max_length=20, choices=MembershipStatus.choices, default=MembershipStatus.INVITED
    )

    class Meta:
        constraints = [models.UniqueConstraint(fields=["org_id", "user"], name="one_membership")]


class Project(TenantModel):
    name = models.CharField(max_length=200)
    client_name = models.CharField(max_length=200, blank=True)
    key = models.CharField(max_length=6, validators=[RegexValidator(r"^[A-Za-z]{2,6}$")])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["org_id", "key"], name="project_key_unique")]


class ProjectMember(TenantModel):
    """Who sees a project; owners and admins see all (DATA §3, §8 rule 3)."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="members")
    user = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "user"], name="one_project_member")
        ]


class AuditEvent(models.Model):
    """Append-only record of changes to what Greenlit claims about quality (DATA §10, FR-ORG-04).

    Not a TenantModel: it has no `updated_at` or `deleted_at`, because rows never change. The
    database refuses UPDATE and DELETE for every role, owners included (migration 0006).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    org_id = models.UUIDField(db_index=True)
    actor = models.ForeignKey("core.User", null=True, on_delete=models.PROTECT, related_name="+")
    action = models.CharField(max_length=100)
    target_type = models.CharField(max_length=100)
    target_id = models.CharField(max_length=100)
    # Only the changed fields, never whole records (DATA §10 rules).
    before = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    after = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    at = models.DateTimeField(default=timezone.now)

    class Meta:
        indexes = [models.Index(fields=["org_id", "target_type", "target_id", "at"])]


class CounterKind(models.TextChoices):
    REQUIREMENT = "REQ"
    TEST_PLAN = "TP"
    TEST_CASE = "TC"
    TEST_RUN = "RUN"
    EVIDENCE = "EV"
    DEFECT = "BUG"
    REPORT = "RPT"


class ProjectCounter(TenantModel):
    """Per-project display-number counters (DATA §4). Never reused, even after deletion."""

    project = models.ForeignKey(Project, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=3, choices=CounterKind.choices)
    next_no = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "kind"], name="one_counter_per_kind")
        ]


class Invitation(TenantModel):
    """An emailed invitation to join an organisation with a chosen role (FR-ORG-01).

    Only the SHA-256 of the token is stored, so a database leak cannot be used to join.
    """

    email = models.EmailField()
    role = models.CharField(max_length=20, choices=Role.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    accepted_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    invited_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")


class JobState(models.TextChoices):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"  # failed an attempt; another is scheduled
    DEAD = "dead"  # gave up; an admin can re-run it


class Job(TenantModel):
    """Background work for one organisation (ARCH §6, DATA §3 `job`).

    `args` hold IDs only and `error` holds an error class or a message written for people,
    never document text (SEC §5).
    """

    kind = models.CharField(max_length=60)
    args = models.JSONField(default=dict, blank=True)
    state = models.CharField(max_length=20, choices=JobState.choices, default=JobState.QUEUED)
    progress = models.JSONField(default=dict, blank=True)
    error = models.CharField(max_length=300, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["org_id", "state", "created_at"])]


class OrgRegistry(models.Model):
    """Organisation IDs only, readable without a scope, so schedulers can fan out per
    organisation (DATA §3). Filled by a database trigger on `organisation`; the app cannot
    write it."""

    organisation_id = models.UUIDField(primary_key=True)
