from django.db import migrations

from apps.core.rls import tenant_table_operations


class Migration(migrations.Migration):
    dependencies = [("files", "0001_stored_file")]

    operations = [
        *tenant_table_operations(
            "files_storedfile", same_org_refs=[("project_id", "core_project")]
        ),
    ]
