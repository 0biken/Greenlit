from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("requirements", "0004_requirement_revision")]

    operations = [
        migrations.RunSQL(
            'ALTER TRIGGER requirements_requirement_source_document_same_org '
            'ON "requirements_requirement" '
            'RENAME TO requirements_requirement_source_document_id_same_org',
            'ALTER TRIGGER requirements_requirement_source_document_id_same_org '
            'ON "requirements_requirement" '
            'RENAME TO requirements_requirement_source_document_same_org',
        ),
    ]
