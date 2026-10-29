from django.apps import AppConfig


class RequirementsConfig(AppConfig):
    name = "apps.requirements"
    label = "requirements"

    def ready(self) -> None:
        from apps.requirements import extraction  # noqa: F401 (registers the extraction job)
