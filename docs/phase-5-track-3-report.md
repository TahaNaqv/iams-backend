# Phase 5 Track 3 — Observability (Complete)

**Date:** 2026-05-13
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 5 Track 3 (NFR-Observability)
**Status:** ✅ Complete

This track turned IAMS from "it works" into "we can see it work." Every request now emits a structured log line, every business event bumps a Prometheus counter, every interesting transition lights up a Grafana panel, and every operational threshold has an alert behind it.

---

## What shipped

### 1. Structured JSON logging — `iams/logging.py`

- `JsonFormatter` emits one JSON object per log record with `time / level / logger / message / request_id / service / host` plus `env` (from `IAMS_LOG_ENV`).
- User-supplied `extra={…}` keys are folded in. Non-serializable values are `repr`'d, never crash the log call.
- Exception tracebacks are captured as a single string field.
- Wired into `LOGGING` as the default formatter; `LOG_FORMAT=text` env switches back for local dev.
- `RequestIdMiddleware` (Phase 1) is already correlating requests; the formatter just surfaces that into the JSON payload.

### 2. Custom Prometheus metrics — `iams/metrics.py`

| Metric | Type | Labels | Producer |
|---|---|---|---|
| `iams_audits_created_total` | counter | `department` | Audit `post_save` |
| `iams_audits_completed_total` | counter | `department` | Audit transition detector |
| `iams_findings_raised_total` | counter | `severity` | Finding `post_save` |
| `iams_caps_created_total` / `iams_caps_closed_total` | counter | — | CAP signals |
| `iams_caps_overdue_current` | **gauge** | — | beat task refresh |
| `iams_approvals_requested_total` / `_approved_total` / `_rejected_total` | counter | `type` | ApprovalRequest signals |
| `iams_approvals_pending_current` | **gauge** | — | beat task refresh |
| `iams_login_attempts_total` | counter | `outcome` | `security.record_login_attempt` |
| `iams_account_lockouts_total` | counter | `reason` | `security.register_failure` |
| `iams_report_jobs_total` / `_completed_total` / `_failed_total` | counter | `kind` | `tasks.reports.generate_report` |

Cardinality is tight: every label is a bounded enum or a small set (~50 departments). No per-id labels.

### 3. Signal-driven increments

Six new handlers in `iams/signals.py` use `pre_save` snapshots + `post_save` transitions to detect "first time entering completed/approved/rejected/closed" status. All wrapped in `_safe_metric` — a metric failure is logged but never reaches the request path. The 5-minute dashboard-cache-refresh beat task additionally calls `refresh_business_gauges()` so the *current* gauges stay accurate after process restarts.

### 4. OpenTelemetry — `iams/telemetry.py`

- `setup_telemetry()` initializes the tracer provider + OTLP/HTTP exporter and auto-instruments Django, Celery, Redis, and Psycopg2 in one place.
- Sampler: `ParentBased(TraceIdRatioBased(0.1))` — child spans honor parent decisions; root spans sample at 10%.
- Idempotent and gated on `OTEL_ENABLED=true`. Off in dev/test by default.
- Wired in `IamsConfig.ready()` so every entry point (`runserver`, `gunicorn`, Celery worker, beat) gets identical setup.

### 5. Grafana + Prometheus assets — `deploy/`

- `grafana/iams-system.json` — req rate, latency p50/95/99, error rate, DB pool, Celery queue depth, login attempts, lockouts.
- `grafana/iams-business.json` — overdue CAPs gauge, approvals pending gauge, daily findings by severity, audit lifecycle, CAP lifecycle, approval flow, report-job pass/fail.
- `prometheus/iams-alerts.yml` — `iams.system` (5xx>1%, p95>1s, Celery backlog, DB errors), `iams.security` (lockout burst, failed-login spike), `iams.business` (overdue CAP threshold, report-job failure rate).
- `deploy/README.md` — operator wiring guide.

---

## Tests

**586/586 passing** (was 573; +13).

The new test file `iams/tests/test_observability.py` covers:

- JSON formatter: required fields, request-id correlation, extras folding, non-serializable repr, exception traceback.
- Business counters: audit created → completed, finding raised by severity, CAP created → closed, approval requested → approved.
- Login-attempt counter (success bumps the counter).
- Gauge refresh syncs from DB state.
- `/metrics` endpoint exposes custom counters in the Prometheus exposition format.

---

## Decisions

- **JSON logs without `python-json-logger`.** A 60-line inline formatter has no surprise behavior and is easy to test (parse → assert). The third-party library adds string-template noise for no benefit.
- **`_safe_metric` decorator wraps every business-metric handler.** Observability must never break the request path. A failed counter increment becomes a log line and a debugger problem, not an HTTP 500.
- **Gauges *and* counters.** "How many overdue right now" is a gauge (refreshed by beat task — slightly stale but bounded). "How many ever-overdue" is meaningless. Conversely "how many CAPs closed" makes sense only as a rate over time — that's a counter.
- **No `user_id`/`audit_id` labels.** Prometheus cardinality is global; one label leak ruins the storage layout. Per-event detail belongs in the audit log + traces, not in time-series.
- **Sampling 10% by default.** Production volume × 100% sampling × 24h retention = a lot of disk. 10% is enough for incident replay; bump for postmortem windows.

---

## What's deferred to infra

- Sentry: SDK init already in `prod.py` from Phase 0 — operator just needs to set `SENTRY_DSN`.
- Loki, Tempo/Jaeger, Prometheus, AlertManager, Grafana: deploy from the operator side using the assets in `deploy/`.
- Uptime Kuma health pings: point at `/health/` and `/ready/` (Phase 0).

---

## What's next in Phase 5

| Track | Title | Status |
|---|---|---|
| 1 | Security | ✅ Complete |
| 2 | Performance & Scale | ✅ Complete |
| 3 | **Observability** | ✅ Complete |
| 4 | CI/CD | ⏳ Next |
