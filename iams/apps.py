from django.apps import AppConfig


class IamsConfig(AppConfig):
    name = "iams"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Connect domain signals → notification dispatch. Import for
        # side-effects only; the @receiver decorators do the wiring.
        from iams import signals  # noqa: F401

        # Phase 5 Track 3 — OpenTelemetry SDK init. No-op when
        # OTEL_ENABLED is unset (dev/test default). Safe to call here
        # because tracer provider setup is idempotent.
        from iams.telemetry import setup_telemetry
        setup_telemetry()
