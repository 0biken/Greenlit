import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

from apps.core.rls import tenant_table_operations, validation_scope


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0013_project_settings"),
        ("requirements", "0003_source_document_and_provenance"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        validation_scope(),
        migrations.CreateModel(
            name="RequirementRevision",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("org_id", models.UUIDField(db_index=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("revision", models.PositiveIntegerField()),
                ("title", models.CharField(max_length=200)),
                ("text", models.TextField()),
                (
                    "priority",
                    models.CharField(
                        choices=[
                            ("critical", "Critical"),
                            ("high", "High"),
                            ("medium", "Medium"),
                            ("low", "Low"),
                        ],
                        max_length=10,
                    ),
                ),
                ("source_locator", models.JSONField(blank=True, default=dict)),
                (
                    "created_by",
                    models.ForeignKey(
                        editable=False,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "requirement",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="revisions",
                        to="requirements.requirement",
                    ),
                ),
                (
                    "source_document",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="requirement_revisions",
                        to="requirements.sourcedocument",
                    ),
                ),
            ],
            options={
                "ordering": ["requirement_id", "revision"],
            },
        ),
        migrations.AddConstraint(
            model_name="requirementrevision",
            constraint=models.UniqueConstraint(
                fields=("requirement", "revision"), name="requirement_revision_unique"
            ),
        ),
        *tenant_table_operations(
            "requirements_requirementrevision",
            app_privileges="SELECT, INSERT",
            same_org_refs=[
                ("requirement_id", "requirements_requirement"),
                ("source_document_id", "requirements_sourcedocument"),
            ],
        ),
        migrations.RunSQL(
            """
            CREATE FUNCTION forbid_requirement_revision_change() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
              RAISE EXCEPTION 'requirement revisions are immutable';
            END;
            $$;
            """,
            "DROP FUNCTION forbid_requirement_revision_change()",
        ),
        migrations.RunSQL(
            """
            CREATE TRIGGER requirement_revision_immutable
            BEFORE UPDATE OR DELETE ON "requirements_requirementrevision"
            FOR EACH ROW EXECUTE FUNCTION forbid_requirement_revision_change()
            """,
            'DROP TRIGGER requirement_revision_immutable ON "requirements_requirementrevision"',
        ),
    ]
