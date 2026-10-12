from django.apps import AppConfig


class SourcesConfig(AppConfig):
    name = "apps.sources"
    label = "sources"

    def ready(self) -> None:
        from apps.files.services import WHEN_AVAILABLE
        from apps.sources import jobs  # registers the parse and draft jobs

        WHEN_AVAILABLE.append(jobs.file_became_available)
