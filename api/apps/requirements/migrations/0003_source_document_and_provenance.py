import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models

from apps.core.rls import tenant_table_operations, validation_scope


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_project_settings"),
        ("requirements", "0002_security"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        validation_scope(),
        migrations.CreateModel(
            name="SourceDocument",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("org_id", models.UUIDField(db_index=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("kind", models.CharField(choices=[("prd", "PRD"), ("screenshot_set", "Screenshot set"), ("qa_report", "QA report")], default="prd", max_length=20)),
                ("title", models.CharField(max_length=200)),
                ("content_text", models.TextField()),
                ("page_count", models.PositiveIntegerField(blank=True, null=True)),
                ("created_by", models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("project", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sources", to="core.project")),
            ],
            options={
                "indexes": [models.Index(fields=["org_id", "project"], name="requirement_org_id_81aade_idx")],
            },
        ),
        migrations.AddField(
            model_name="requirement",
            name="source_document",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="requirements", to="requirements.sourcedocument"),
        ),
        *tenant_table_operations(
            "requirements_sourcedocument",
            same_org_refs=[("project_id", "core_project")],
        ),
        migrations.RunSQL(
            'CREATE TRIGGER requirements_requirement_source_document_same_org '
            'BEFORE INSERT OR UPDATE ON "requirements_requirement" '
            "FOR EACH ROW EXECUTE FUNCTION enforce_same_org('requirements_sourcedocument', 'source_document_id')",
            'DROP TRIGGER requirements_requirement_source_document_same_org ON "requirements_requirement"',
        ),
    ]
