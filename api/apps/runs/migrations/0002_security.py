from django.db import migrations

from apps.core.rls import tenant_table_operations


class Migration(migrations.Migration):
    dependencies = [
        ("runs", "0001_initial"),
    ]

    operations = [
        *tenant_table_operations(
            "runs_release",
            same_org_refs=[("project_id", "core_project")],
        ),
        *tenant_table_operations(
            "runs_testrun",
            same_org_refs=[("project_id", "core_project"), ("release_id", "runs_release"), ("plan_version_id", "plans_planversion")],
        ),
        *tenant_table_operations(
            "runs_caseresult",
            same_org_refs=[("run_id", "runs_testrun"), ("case_revision_id", "plans_caserevision")],
        ),
        *tenant_table_operations(
            "runs_evidence",
            same_org_refs=[("project_id", "core_project"), ("file_id", "files_storedfile")],
        ),
        *tenant_table_operations(
            "runs_evidencelink",
            same_org_refs=[("evidence_id", "runs_evidence")],
        ),
    ]
