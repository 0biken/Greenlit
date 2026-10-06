from django.db import migrations

from apps.core.rls import APP_ROLE, ORG_TABLE, create_functions, tenant_table_operations

# Members and organisations must be readable before an organisation is chosen, so their
# policies also allow a user to see their own memberships (and the organisations those
# belong to). Writes still need the organisation scope.
MEMBERSHIP_USING = "org_id = app_current_org_or_null() OR user_id = app_current_user()"
ORGANISATION_USING = (
    "id = app_current_org_or_null() OR id IN "
    "(SELECT org_id FROM core_membership WHERE user_id = app_current_user())"
)


class Migration(migrations.Migration):
    dependencies = [("core", "0002_account_tables")]

    operations = [
        migrations.RunSQL(
            f"""
            DO $$ BEGIN
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS;
              END IF;
            END $$;
            GRANT USAGE ON SCHEMA public TO {APP_ROLE};
            GRANT SELECT, INSERT, UPDATE ON core_user TO {APP_ROLE};
            """,
            migrations.RunSQL.noop,
        ),
        create_functions(),
        *tenant_table_operations(ORG_TABLE, policy_using=ORGANISATION_USING),
        *tenant_table_operations("core_membership", policy_using=MEMBERSHIP_USING),
        *tenant_table_operations("core_project"),
        *tenant_table_operations(
            "core_projectmember", same_org_refs=[("project_id", "core_project")]
        ),
    ]
