from django.apps import AppConfig


class IamsConfig(AppConfig):
    name = "iams"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Connect domain signals → notification dispatch. Import for
        # side-effects only; the @receiver decorators do the wiring.
        from iams import signals  # noqa: F401
