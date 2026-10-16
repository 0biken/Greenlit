from django.apps import AppConfig


class PlansConfig(AppConfig):
    name = "apps.plans"
    label = "plans"

    def ready(self) -> None:
        from apps.plans import drafting  # noqa: F401  (registers the draft_cases job)
