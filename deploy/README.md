# IAMS Operations Artifacts

Observability-as-code (Phase 5 Track 3). Drop these files into the production observability stack.

## `grafana/`

- `iams-system.json` — request rate, latency p50/95/99, error rate, DB pool, Celery queue depth, login attempts, lockouts.
- `iams-business.json` — overdue CAPs gauge, approvals pending gauge, daily findings by severity, audits / CAPs / approvals flow, report-job pass-fail.

Provision via Grafana's file-based provisioning (`/etc/grafana/provisioning/dashboards/`) or import in the UI.

## `prometheus/`

- `iams-alerts.yml` — recording + alert rules grouped into `iams.system`, `iams.security`, `iams.business`.

Wire into Prometheus via `rule_files: ["/etc/prometheus/iams-alerts.yml"]`. Route the `severity=page` alerts to PagerDuty / oncall; `warn` to Slack.

## Wiring summary

| Signal | Producer | Consumer |
|---|---|---|
| Structured JSON logs (stdout) | Django + Celery (`iams.logging.JsonFormatter`) | Promtail → Loki |
| `/metrics/` Prometheus scrape | `django_prometheus` + `iams.metrics` | Prometheus |
| OTLP traces | `iams.telemetry.setup_telemetry()` | Tempo / Jaeger |
| Errors | `sentry-sdk` in `prod.py` | self-hosted Sentry |
| Liveness / readiness | `/health/`, `/ready/` | Uptime Kuma |

## Environment knobs

```env
LOG_FORMAT=json                  # or "text" for local dev
IAMS_LOG_ENV=prod                # surfaces as ``env`` field

OTEL_ENABLED=true
OTEL_SERVICE_NAME=iams-backend
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4318
OTEL_TRACES_SAMPLER_ARG=0.1

SENTRY_DSN=https://...
SENTRY_TRACES_SAMPLE_RATE=0.1
```
