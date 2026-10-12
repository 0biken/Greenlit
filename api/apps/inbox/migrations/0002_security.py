from django.db import migrations

from apps.core.rls import tenant_table_operations


class Migration(migrations.Migration):
    dependencies = [
        ("inbox", "0001_initial"),
    ]

    operations = [
        *tenant_table_operations(
            "inbox_snooze",
        ),
    ]
