from django.db import migrations

from apps.core.rls import tenant_table_operations


# A published plan version never changes: only its move to superseded is allowed. The cases
# it lists, and the case revisions they point at, are frozen with it (M3-01, DATA §6).
FREEZE_PUBLISHED = """
CREATE FUNCTION plans_refuse_published_version() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.state = 'draft' THEN
    RETURN COALESCE(NEW, OLD);
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.state = 'published' AND NEW.state = 'superseded'
     AND NEW.number = OLD.number AND NEW.plan_id = OLD.plan_id
     AND NEW.approved_by_id IS NOT DISTINCT FROM OLD.approved_by_id
     AND NEW.approved_at IS NOT DISTINCT FROM OLD.approved_at
     AND NEW.deleted_at IS NOT DISTINCT FROM OLD.deleted_at THEN
    RETURN NEW;
  END IF;
  RAISE EXCEPTION 'published plan versions cannot change' USING ERRCODE = 'check_violation';
END $$;
CREATE TRIGGER plans_planversion_frozen BEFORE UPDATE OR DELETE ON plans_planversion
  FOR EACH ROW EXECUTE FUNCTION plans_refuse_published_version();

CREATE FUNCTION plans_refuse_published_membership() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v uuid := CASE WHEN TG_OP = 'DELETE' THEN OLD.plan_version_id ELSE NEW.plan_version_id END;
BEGIN
  IF EXISTS (SELECT 1 FROM plans_planversion WHERE id = v AND state <> 'draft')
     OR (TG_OP = 'UPDATE' AND EXISTS (
       SELECT 1 FROM plans_planversion WHERE id = OLD.plan_version_id AND state <> 'draft')) THEN
    RAISE EXCEPTION 'cases of a published plan version cannot change'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER plans_planversioncase_frozen BEFORE INSERT OR UPDATE OR DELETE
  ON plans_planversioncase FOR EACH ROW EXECUTE FUNCTION plans_refuse_published_membership();

CREATE FUNCTION plans_refuse_used_revision() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM plans_planversioncase pvc
    JOIN plans_planversion pv ON pv.id = pvc.plan_version_id
    WHERE pvc.case_revision_id = OLD.id AND pv.state <> 'draft'
  ) THEN
    RAISE EXCEPTION 'case revisions used by a published plan version cannot change'
      USING ERRCODE = 'check_violation';
  END IF;
  RETURN COALESCE(NEW, OLD);
END $$;
CREATE TRIGGER plans_caserevision_frozen BEFORE UPDATE OR DELETE ON plans_caserevision
  FOR EACH ROW EXECUTE FUNCTION plans_refuse_used_revision();
"""

UNFREEZE = """
DROP TRIGGER plans_caserevision_frozen ON plans_caserevision;
DROP FUNCTION plans_refuse_used_revision();
DROP TRIGGER plans_planversioncase_frozen ON plans_planversioncase;
DROP FUNCTION plans_refuse_published_membership();
DROP TRIGGER plans_planversion_frozen ON plans_planversion;
DROP FUNCTION plans_refuse_published_version();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("plans", "0002_initial"),
    ]

    operations = [
        *tenant_table_operations(
            "plans_testplan",
            same_org_refs=[("project_id", "core_project"), ("current_version_id", "plans_planversion")],
        ),
        *tenant_table_operations(
            "plans_planversion",
            same_org_refs=[("plan_id", "plans_testplan")],
        ),
        *tenant_table_operations(
            "plans_testcase",
            same_org_refs=[("project_id", "core_project")],
        ),
        *tenant_table_operations(
            "plans_caserevision",
            same_org_refs=[("test_case_id", "plans_testcase")],
        ),
        *tenant_table_operations(
            "plans_planversioncase",
            same_org_refs=[("plan_version_id", "plans_planversion"), ("case_revision_id", "plans_caserevision")],
        ),
        *tenant_table_operations(
            "plans_caserequirement",
            same_org_refs=[("case_revision_id", "plans_caserevision"), ("requirement_id", "requirements_requirement")],
        ),
        migrations.RunSQL(FREEZE_PUBLISHED, UNFREEZE),
    ]
