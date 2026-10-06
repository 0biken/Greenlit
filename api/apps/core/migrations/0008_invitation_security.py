from django.db import migrations

from apps.core.rls import tenant_table_operations

# Someone holding an invitation token must be able to read that one invitation before they
# belong to the organisation. The app sets `app.invite_hash` to the hash of the token it was
# given, and the policy matches on equality, so only the holder of the token can see the row.
# Writes still need the organisation scope.
INVITE_HASH_FUNCTION = """
CREATE FUNCTION app_current_invite_hash() RETURNS text LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.invite_hash', true), '')
$$
"""

INVITATION_USING = "org_id = app_current_org_or_null() OR token_hash = app_current_invite_hash()"


class Migration(migrations.Migration):
    dependencies = [("core", "0007_invitation")]

    operations = [
        migrations.RunSQL(INVITE_HASH_FUNCTION, "DROP FUNCTION app_current_invite_hash()"),
        *tenant_table_operations(
            "core_invitation", policy_using=INVITATION_USING
        ),
    ]
