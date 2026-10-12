from django.db import migrations

from apps.core.rls import tenant_table_operations


class Migration(migrations.Migration):
    dependencies = [
        ("requirements", "0001_initial"),
    ]

    operations = [
        *tenant_table_operations(
            "requirements_requirement",
            same_org_refs=[("project_id", "core_project")],
        ),
    ]
