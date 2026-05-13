"""OpenTelemetry initialization (Phase 5 Track 3).

Distributed tracing for IAMS — spans flow from the FE request through
Django, into Celery tasks, and out to Postgres / Redis. Exporter is
OTLP/HTTP by default (Tempo or Jaeger native OTLP receiver).

Wired in via ``IamsConfig.ready()`` so every entry point — `runserver`,
`gunicorn`, Celery worker, Celery beat — gets a single, consistent
setup. Guarded by ``OTEL_ENABLED=true``; off in dev/test by default.

Sample rate is conservative (``OTEL_TRACES_SAMPLER_ARG=0.1`` by
default) so production traffic doesn't drown the collector.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_initialized = False


def setup_telemetry() -> bool:
    """Initialize OTel SDK + Django/Celery/Postgres/Redis auto-instrumentation.

    Returns True if telemetry is now wired, False if disabled or init
    failed. Idempotent — calling twice is a no-op.
    """
    global _initialized
    if _initialized:
        return True

    if os.environ.get("OTEL_ENABLED", "").lower() not in ("1", "true", "yes"):
        logger.info("otel: disabled (OTEL_ENABLED not set)")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.celery import CeleryInstrumentor
        from opentelemetry.instrumentation.django import DjangoInstrumentor
        from opentelemetry.instrumentation.redis import RedisInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import (
            ParentBased,
            TraceIdRatioBased,
        )
    except ImportError:
        logger.exception("otel: SDK packages missing; tracing disabled")
        return False

    service_name = os.environ.get("OTEL_SERVICE_NAME", "iams-backend")
    sample_rate = float(os.environ.get("OTEL_TRACES_SAMPLER_ARG", "0.1"))

    resource = Resource.create(
        {
            "service.name": service_name,
            "service.namespace": os.environ.get("OTEL_NAMESPACE", "iams"),
            "deployment.environment": os.environ.get("IAMS_LOG_ENV", ""),
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBased(root=TraceIdRatioBased(sample_rate)),
    )
    # Default OTLP/HTTP endpoint: http://otel-collector:4318/v1/traces
    # Override via OTEL_EXPORTER_OTLP_ENDPOINT.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    # Django instrumentation hooks request/response cycle.
    DjangoInstrumentor().instrument()
    # Celery tasks: parent-child relationship via OTel context propagation.
    CeleryInstrumentor().instrument()
    # Redis spans: cache hits/misses + lock waits.
    RedisInstrumentor().instrument()

    # Psycopg2 is optional — skip if not installed (dev SQLite environment).
    try:
        from opentelemetry.instrumentation.psycopg2 import Psycopg2Instrumentor
        Psycopg2Instrumentor().instrument()
    except (ImportError, Exception):  # noqa: BLE001
        logger.debug("otel: psycopg2 instrumentation skipped (driver absent)")

    _initialized = True
    logger.info(
        "otel: initialized service=%s sample_rate=%.2f endpoint=%s",
        service_name, sample_rate,
        os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "<default>"),
    )
    return True
