"""No foreign key can point into another organisation (M1-05, DATA §8 rule 4).

Each foreign key from one tenant table to another needs the `same_org` trigger that
`tenant_table_operations(..., same_org_refs=[...])` installs (apps/core/rls.py). This test finds
every such key from the models, so a new table that forgets it fails the build.
"""

import pytest
from django.apps import apps
from django.db import connection

pytestmark = pytest.mark.django_db


def is_tenant(model) -> bool:
    return any(f.column == "org_id" for f in model._meta.concrete_fields)


def tenant_foreign_keys() -> list[tuple[str, str, str]]:
    """(table, column, referenced table) for every FK between two tenant tables."""
    found = []
    for model in apps.get_models():
        if not is_tenant(model) or not model._meta.managed:
            continue
        for field in model._meta.concrete_fields:
            if field.is_relation and field.many_to_one and is_tenant(field.related_model):
                found.append(
                    (model._meta.db_table, field.column, field.related_model._meta.db_table)
                )
    return sorted(found)


def triggers() -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
        return {row[0] for row in cursor.fetchall()}


def test_the_check_sees_the_keys_that_exist_today():
    keys = tenant_foreign_keys()
    assert ("core_projectmember", "project_id", "core_project") in keys
    assert ("files_storedfile", "project_id", "core_project") in keys
    # Keys to users are global, not tenant-to-tenant, so they are not in the list.
    assert not [k for k in keys if k[2] == "core_user"]


def test_every_foreign_key_between_tenant_tables_has_the_same_organisation_trigger():
    installed = triggers()
    missing = [
        f"{table}.{column} -> {target}"
        for table, column, target in tenant_foreign_keys()
        if f"{table}_{column}_same_org" not in installed
    ]
    assert missing == [], (
        "These foreign keys can point into another organisation. Add them to `same_org_refs` "
        "in the table's tenant_table_operations(...) migration: " + "; ".join(missing)
    )
