"""Row-level security helpers for migrations (DATA §8, SEC §5).

Every tenant table gets, in the migration that creates it:

    operations = [
        *tenant_table_operations(
            "plans_testplan", same_org_refs=[("project_id", "core_project")]
        ),
    ]

That enables and forces RLS with a policy keyed on `org_id`, adds a foreign key from
`org_id` to the organisation, grants the app role its table privileges, and installs
triggers so a foreign key can never point at a row of another organisation.
"""

from django.db import migrations

APP_ROLE = "greenlit_app"

# `app_current_org()` raises when the scope is missing, so a query made without an
# organisation fails instead of returning rows.
FUNCTIONS_SQL = """
CREATE FUNCTION app_current_org() RETURNS uuid LANGUAGE plpgsql STABLE AS $$
DECLARE v text := current_setting('app.org_id', true);
BEGIN
  IF v IS NULL OR v = '' THEN
    RAISE EXCEPTION 'app.org_id is not set: no organisation scope for this query';
  END IF;
  RETURN v::uuid;
END $$;

CREATE FUNCTION app_current_org_or_null() RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.org_id', true), '')::uuid
$$;

CREATE FUNCTION app_current_user() RETURNS uuid LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.user_id', true), '')::uuid
$$;

CREATE FUNCTION enforce_same_org() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  ref_id text := to_jsonb(NEW) ->> TG_ARGV[1];
  ref_org uuid;
BEGIN
  IF ref_id IS NULL THEN
    RETURN NEW;
  END IF;
  EXECUTE format('SELECT org_id FROM %I WHERE id = $1', TG_ARGV[0])
    INTO ref_org USING ref_id::uuid;
  IF ref_org IS DISTINCT FROM NEW.org_id THEN
    RAISE EXCEPTION 'cross-organisation reference: %.% points outside organisation %',
      TG_TABLE_NAME, TG_ARGV[1], NEW.org_id;
  END IF;
  RETURN NEW;
END $$;
"""

DROP_FUNCTIONS_SQL = """
DROP FUNCTION enforce_same_org();
DROP FUNCTION app_current_user();
DROP FUNCTION app_current_org_or_null();
DROP FUNCTION app_current_org();
"""

ORG_TABLE = "core_organisation"


def create_functions() -> migrations.RunSQL:
    return migrations.RunSQL(FUNCTIONS_SQL, DROP_FUNCTIONS_SQL)


def tenant_table_operations(
    table: str,
    *,
    policy_using: str | None = None,
    same_org_refs: list[tuple[str, str]] | None = None,
    app_privileges: str = "SELECT, INSERT, UPDATE, DELETE",
) -> list[migrations.RunSQL]:
    """SQL operations that make `table` a tenant table.

    `policy_using` overrides the default `org_id = app_current_org()` predicate for the few
    tables that must be readable before an organisation is chosen (organisation, membership).
    `same_org_refs` lists (fk_column, referenced_table) pairs that must stay in one organisation.
    `app_privileges` is what the app role may do; append-only tables grant "SELECT, INSERT".
    """
    using = policy_using or "org_id = app_current_org()"
    # Writes always need the organisation scope, even where reads are wider.
    check = "org_id = app_current_org()"

    forward: list[str] = []
    reverse: list[str] = []  # in undo order: last step first

    # The foreign key goes first: adding it validates rows, and forced RLS would block that.
    if table != ORG_TABLE:
        forward.append(
            f'ALTER TABLE "{table}" ADD CONSTRAINT {table}_org_fk '
            f'FOREIGN KEY (org_id) REFERENCES "{ORG_TABLE}" (id) DEFERRABLE INITIALLY DEFERRED'
        )
        reverse.append(f'ALTER TABLE "{table}" DROP CONSTRAINT {table}_org_fk')

    forward += [
        f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY',
        f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY',
        f'CREATE POLICY tenant_isolation ON "{table}" USING ({using}) WITH CHECK ({check})',
        f'GRANT {app_privileges} ON "{table}" TO {APP_ROLE}',
    ]
    reverse = [
        f'DROP POLICY tenant_isolation ON "{table}"',
        f'ALTER TABLE "{table}" NO FORCE ROW LEVEL SECURITY',
        f'ALTER TABLE "{table}" DISABLE ROW LEVEL SECURITY',
        *reverse,
    ]

    for column, ref_table in same_org_refs or []:
        trigger = f"{table}_{column}_same_org"
        forward.append(
            f'CREATE TRIGGER {trigger} BEFORE INSERT OR UPDATE ON "{table}" '
            f"FOR EACH ROW EXECUTE FUNCTION enforce_same_org('{ref_table}', '{column}')"
        )
        reverse.insert(0, f'DROP TRIGGER {trigger} ON "{table}"')

    return [migrations.RunSQL("; ".join(forward), "; ".join(reverse))]


def validation_scope() -> migrations.RunSQL:
    """Give the rest of this migration's transaction a throwaway organisation scope.

    Adding a foreign key to a table that already has forced RLS makes Postgres run a validation
    query that evaluates the policy, which fails without a scope. Put this first in any
    migration that creates a table with a foreign key to a tenant table. It is only correct for
    new, empty tables: against existing rows the nil scope hides every referenced row. For
    those, add the key with `db_constraint=False` and rely on `same_org_refs` instead.
    """
    return migrations.RunSQL(
        "SELECT set_config('app.org_id', '00000000-0000-0000-0000-000000000000', true)",
        migrations.RunSQL.noop,
    )
