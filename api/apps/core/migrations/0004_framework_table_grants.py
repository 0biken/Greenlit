from django.db import migrations

from apps.core.rls import APP_ROLE

# The running app connects as a restricted role (SEC §5), so every table it touches needs an
# explicit grant. Relying on default privileges would work on one database and fail on the next.
# Not granted on purpose: django_migrations and django_admin_log.
READ_WRITE = [
    "django_session",
    "account_emailaddress",
    "account_emailconfirmation",
    "socialaccount_socialaccount",
    "socialaccount_socialtoken",
    "core_user_groups",
    "core_user_user_permissions",
]
READ_ONLY = [
    "django_content_type",
    "django_site",
    "auth_permission",
    "auth_group",
    "auth_group_permissions",
    "socialaccount_socialapp",
    "socialaccount_socialapp_sites",
]


def statements(verb_and_privs: str, tables: list[str], preposition: str) -> str:
    return "; ".join(f'{verb_and_privs} ON "{t}" {preposition} {APP_ROLE}' for t in tables)


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0003_row_level_security"),
        ("sessions", "0001_initial"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("sites", "0002_alter_domain_unique"),
        ("account", "0001_initial"),
        ("socialaccount", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            statements("GRANT SELECT, INSERT, UPDATE, DELETE", READ_WRITE, "TO")
            + "; "
            + statements("GRANT SELECT", READ_ONLY, "TO"),
            statements("REVOKE ALL PRIVILEGES", READ_WRITE + READ_ONLY, "FROM"),
        ),
    ]
