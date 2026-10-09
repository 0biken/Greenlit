"""Seed a local database: two organisations, members of every role, and projects (TASKS M1-20).

Run with the owner role (see CLAUDE.md). Safe to run again: everything is get-or-create.
Karma Groups is the default organisation; Globex is the second tenant the isolation work needs.
"""

from allauth.account.models import EmailAddress
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from apps.core.models import Membership, MembershipStatus, Project, Role
from apps.core.services import ServiceError, create_organisation
from apps.core.tenancy import org_scope

User = get_user_model()

PASSWORD = "password1234"  # noqa: S105 - local development seed only

KARMA = {"name": "Karma Groups", "slug": "karma-groups", "domain": "karmagroups.example"}
KARMA_MEMBERS = [
    ("admin", "Karma Admin", Role.ADMIN),
    ("lead", "Ngozi Eze", Role.QA_LEAD),
    ("qa", "Ada Okafor", Role.QA_ENGINEER),
    ("dev", "Femi Adeyemi", Role.DEVELOPER),
    ("viewer", "Tunde Bello", Role.VIEWER),
]
# Keys match the mock layer in web/src/mocks, so the dashboards line up with real projects.
KARMA_PROJECTS = [
    ("HUBE", "Hube checkout", "Hube Retail"),
    ("KOLA", "Kola banking app", "Kola Finance"),
    ("MARA", "Mara bookings", "Mara Travel"),
]


def _ensure_user(email, name, password=PASSWORD):
    user, _ = User.objects.get_or_create(email=email, defaults={"name": name})
    user.set_password(password)
    user.save()
    EmailAddress.objects.get_or_create(
        user=user, email=email, defaults={"primary": True, "verified": True}
    )
    EmailAddress.objects.filter(user=user, email=email).update(verified=True)
    return user


def _org_id(owner, name, slug):
    """Create the organisation, or find it by slug if an earlier run made it."""
    try:
        return create_organisation(owner, name, slug).id
    except ServiceError:
        # Row-level security shows an organisation only to its members, so look it up as
        # the owner (app.user_id), for this transaction only.
        with connection.cursor() as cursor:
            cursor.execute("SELECT set_config('app.user_id', %s, true)", [str(owner.pk)])
            cursor.execute("SELECT id FROM core_organisation WHERE slug = %s", [slug])
            row = cursor.fetchone()
            cursor.execute("SELECT set_config('app.user_id', '', true)")
        return row[0] if row else None


class Command(BaseCommand):
    help = "Seeds the database with test data for local development"

    def handle(self, *args, **options):
        self.stdout.write("Seeding database...")
        domain = KARMA["domain"]

        with transaction.atomic():
            owner = _ensure_user(f"owner@{domain}", "Karma Owner")
            karma_id = _org_id(owner, KARMA["name"], KARMA["slug"])
            if karma_id:
                with org_scope(karma_id, owner.pk):
                    Membership.objects.get_or_create(
                        org_id=karma_id,
                        user=owner,
                        defaults={"role": Role.OWNER, "status": MembershipStatus.ACTIVE},
                    )
                    for local, name, role in KARMA_MEMBERS:
                        user = _ensure_user(f"{local}@{domain}", name)
                        Membership.objects.get_or_create(
                            org_id=karma_id,
                            user=user,
                            defaults={"role": role, "status": MembershipStatus.ACTIVE},
                        )
                    for key, name, client in KARMA_PROJECTS:
                        Project.objects.get_or_create(
                            org_id=karma_id, key=key, defaults={"name": name, "client_name": client}
                        )

            globex_owner = _ensure_user("scorpio@globex.example", "Hank Scorpio")
            globex_id = _org_id(globex_owner, "Globex Corporation", "globex")
            if globex_id:
                with org_scope(globex_id, globex_owner.pk):
                    Project.objects.get_or_create(
                        org_id=globex_id, key="ARC", defaults={"name": "Project Arcturus"}
                    )

        self.stdout.write(self.style.SUCCESS("Database seeded."))
        self.stdout.write(
            f"Sign in as owner@{domain} (or admin@, lead@, qa@, dev@, viewer@) "
            f"with password {PASSWORD}."
        )
