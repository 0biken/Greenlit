from django.db import migrations

from apps.core.rls import APP_ROLE, tenant_table_operations

# The registry is filled by a trigger that runs with the migration role's rights (SECURITY
# DEFINER), so the app role only ever reads it. There is no backfill: no environment held
# organisations before this migration, and copying them would mean switching off row-level
# security, which migrations must never do (CI checks for it).
REGISTRY_SQL = f"""
CREATE FUNCTION register_organisation() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
BEGIN
  INSERT INTO core_orgregistry (organisation_id) VALUES (NEW.id) ON CONFLICT DO NOTHING;
  RETURN NEW;
END $$;

CREATE TRIGGER core_organisation_registry
  AFTER INSERT ON core_organisation
  FOR EACH ROW EXECUTE FUNCTION register_organisation();

REVOKE ALL ON core_orgregistry FROM {APP_ROLE};
GRANT SELECT ON core_orgregistry TO {APP_ROLE};
"""

DROP_SQL = """
DROP TRIGGER core_organisation_registry ON core_organisation;
DROP FUNCTION register_organisation();
"""


class Migration(migrations.Migration):
    dependencies = [("core", "0011_jobs")]

    operations = [
        *tenant_table_operations("core_job"),
        migrations.RunSQL(REGISTRY_SQL, DROP_SQL),
    ]
