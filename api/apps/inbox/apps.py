from django.apps import AppConfig


class InboxConfig(AppConfig):
    name = "apps.inbox"
    label = "inbox"

    def ready(self) -> None:
        from apps.inbox import jobs  # noqa: F401  (registers the reminders and digest jobs)
