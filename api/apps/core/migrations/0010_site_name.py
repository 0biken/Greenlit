from urllib.parse import urlparse

from django.conf import settings
from django.db import migrations


def name_the_site(apps, schema_editor):
    """allauth puts the site's name and domain in its emails; the default is `example.com`."""
    Site = apps.get_model("sites", "Site")
    domain = urlparse(settings.FRONTEND_URL).netloc or "localhost"
    Site.objects.update_or_create(
        pk=settings.SITE_ID, defaults={"name": "Greenlit", "domain": domain}
    )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0009_auth_table_grants"),
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [migrations.RunPython(name_the_site, migrations.RunPython.noop)]
