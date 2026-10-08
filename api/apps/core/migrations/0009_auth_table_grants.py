from django.db import migrations

from apps.core.rls import APP_ROLE

# Tables added by allauth.mfa and allauth.usersessions. The running app uses a restricted role
# (SEC §5), so each table it touches needs an explicit grant (see 0004).
TABLES = ["mfa_authenticator", "usersessions_usersession"]


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0008_invitation_security"),
        ("mfa", "0003_authenticator_type_uniq"),
        ("usersessions", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(
            "; ".join(f'GRANT SELECT, INSERT, UPDATE, DELETE ON "{t}" TO {APP_ROLE}' for t in TABLES),
            "; ".join(f'REVOKE ALL PRIVILEGES ON "{t}" FROM {APP_ROLE}' for t in TABLES),
        ),
    ]
