from django.db import migrations

from apps.core.rls import tenant_table_operations


# A signed report is a frozen copy: never recomputed, never edited (DATA §3).
FREEZE_SIGNED = """
CREATE FUNCTION reports_refuse_signed_report() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.state = 'signed' THEN
    RAISE EXCEPTION 'signed reports cannot change' USING ERRCODE = 'check_violation';
  END IF;
  RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER reports_report_frozen BEFORE UPDATE OR DELETE ON reports_report
  FOR EACH ROW EXECUTE FUNCTION reports_refuse_signed_report();
"""

UNFREEZE = """
DROP TRIGGER reports_report_frozen ON reports_report;
DROP FUNCTION reports_refuse_signed_report();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("reports", "0002_initial"),
    ]

    operations = [
        *tenant_table_operations(
            "reports_report",
            same_org_refs=[("project_id", "core_project"), ("release_id", "runs_release")],
        ),
        *tenant_table_operations(
            "reports_signoff",
            same_org_refs=[("release_id", "runs_release"), ("report_id", "reports_report")],
            app_privileges="SELECT, INSERT",
        ),
        migrations.RunSQL(FREEZE_SIGNED, UNFREEZE),
    ]
