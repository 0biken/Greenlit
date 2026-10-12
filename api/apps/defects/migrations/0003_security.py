from django.db import migrations

from apps.core.rls import tenant_table_operations


class Migration(migrations.Migration):
    dependencies = [
        ("defects", "0002_initial"),
    ]

    operations = [
        *tenant_table_operations(
            "defects_defect",
            same_org_refs=[("project_id", "core_project"), ("release_id", "runs_release"), ("found_in_result_id", "runs_caseresult")],
        ),
        *tenant_table_operations(
            "defects_retest",
            same_org_refs=[("defect_id", "defects_defect")],
            app_privileges="SELECT, INSERT",
        ),
    ]
