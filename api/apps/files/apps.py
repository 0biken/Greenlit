from django.apps import AppConfig


class FilesConfig(AppConfig):
    name = "apps.files"
    label = "files"

    def ready(self) -> None:
        from apps.files import services  # noqa: F401  (registers the scan_file job)
