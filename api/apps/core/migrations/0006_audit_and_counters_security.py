from django.db import migrations

from apps.core.rls import tenant_table_operations

FORBID_MUTATION = """
CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP;
END $$;

CREATE TRIGGER core_auditevent_append_only
  BEFORE UPDATE OR DELETE ON core_auditevent
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation()
"""

DROP_FORBID_MUTATION = """
DROP TRIGGER core_auditevent_append_only ON core_auditevent;
DROP FUNCTION forbid_mutation()
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0005_audit_and_counters")]

    operations = [
        # Append-only: the app role can read and insert, and a trigger refuses UPDATE and DELETE
        # for every role, owners included (DATA §10).
        *tenant_table_operations("core_auditevent", app_privileges="SELECT, INSERT"),
        migrations.RunSQL(FORBID_MUTATION, DROP_FORBID_MUTATION),
        *tenant_table_operations(
            "core_projectcounter", same_org_refs=[("project_id", "core_project")]
        ),
    ]
