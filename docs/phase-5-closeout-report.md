# Phase 5 — Close-Out Report

**Date:** 2026-05-13
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 5
**Status:** ✅ Complete

Phase 5 ("Enterprise Hardening") took IAMS from "feature-complete" to **operable**: authentication is enterprise-grade, performance is bounded by query-budget regression tests, observability is end-to-end, and the deploy pipeline is fail-closed with backup/restore drills.

---

## Tracks shipped

| # | Title | Version | Tests added |
|---|---|---|---:|
| 1 | Security Hardening | `0.16.0` | +24 |
| 2 | Performance & Scale | `0.17.0` | +9 |
| 3 | Observability | `0.18.0` | +13 |
| 4 | CI/CD | `0.19.0` | 0 |
| **Phase 5 total** | | | **+46** |

Test suite: **540 → 586** (all green with `IAMS_DISABLE_PDF_RENDER=1`).

---

## What changed for the product

### For Security & Compliance
- **MFA (TOTP)**, per-role enforceable. Backup codes (one-shot, hashed). Login attempts logged with IP / UA / request-id. Account lockouts after 5 failures, configurable. Password history of 5 (no reuse). Hardened JWT login returns precise error codes (`account_locked`, `mfa_required`, `mfa_invalid`).
- **Defense-in-depth headers** on every response: CSP, Permissions-Policy, COOP/CORP, Referrer-Policy.
- **Audit-grade login ledger** — every authentication outcome has a `LoginAttempt` row with the request metadata, queryable for forensics.

### For Operations
- **Structured JSON logs** with request-id correlation, ready for Promtail → Loki.
- **`/metrics/`** exposes 13 business counters + 2 live-state gauges (Prometheus exposition format). Grafana boards for system + business in [`deploy/grafana/`](../deploy/grafana/).
- **OTel SDK** with auto-instrumented Django / Celery / Redis / Psycopg2; 10% default sampling; OTLP/HTTP exporter.
- **Alert rules** for 5xx > 1%, p95 > 1s, Celery backlog > 1000, DB errors, lockout burst, failed-login spike, overdue CAPs, report-job failure rate.

### For Performance
- **Default page size 100 → 25** (NFR target).
- **9 composite indexes** on dashboard / overdue-scan hot paths.
- **2 N+1 fixes** on `Notification` + `AuditLog` GFK serializers.
- **Query-budget regression tests** with `CaptureQueriesContext`: every list endpoint bounded ≤ 12 queries.
- **Locust scenario** ready against staging at 500 concurrent users.

### For Reliability
- **Blue-green deploy** with migration-before-flip safety and atomic nginx upstream symlink swap.
- **Fail-closed**: broken migration / failed health check / Trivy CRITICAL — none of these reach prod traffic.
- **Encrypted backups** to NAS + offsite (`pg_dump` + `age` + `restic`) with retention. Restore script + quarterly drill.
- **Migration checklist** codifying the N-1 rule.

---

## Architectural decisions worth recording

1. **Observability is best-effort.** Every business-metric handler is wrapped in `_safe_metric`. A failed counter increment is a log line, not an HTTP 500. The same rule applies to login-attempt recording — auth must never break because an audit row failed.
2. **Cardinality discipline.** All Prometheus labels are bounded enums (status, severity, outcome, kind, reason, type, department). No per-id labels — that's what the audit log + traces are for.
3. **`migrate` runs inside the new color, before traffic flips.** A broken migration takes the deploy down, not the system. Combined with the migration checklist's N-1 rule, this lets us do safe schema changes during business hours.
4. **`CaptureQueriesContext` over runtime N+1 detectors.** Explicit query budgets in tests fail with a legible message; nplusone-style middleware emits log noise that nobody reads.
5. **Per-color migration + symlink-swap blue-green, not Kubernetes.** The plan is explicit about on-prem docker-compose. `ln -sfn` + `nginx -s reload` is atomic enough; the rolling-K8s story is Phase 6+.

---

## What's deferred to operator

- Provisioning Harbor / Gitea Actions runner / Vault on-prem.
- Setting GitHub secrets (`STAGING_HOST`, `PROD_HOST`, `*_DEPLOY_KEY`, `REGISTRY_USERNAME`, `REGISTRY_PASSWORD`, `SENTRY_DSN`).
- Creating the `staging` / `production` protected environments with required reviewers.
- Generating age recipient keys + provisioning restic repos.
- Cron entry for `deploy/backup.sh`.
- Scheduling the quarterly restore drill.
- Wiring Loki / Tempo / Prometheus / AlertManager / Grafana using the assets in `deploy/`.

---

## What's next: Phase 6 — Integrations & Polish

| Track | Title | Notes |
|---|---|---|
| 1 | SSO via Keycloak | OIDC, AD/LDAP federation, JIT user provisioning, group→role mapping |
| 2 | ERP / HR integrations | Inbound `auditable_entity`/`finding` from SAP / Oracle / Odoo; outbound `users` from AD/HRIS |
| 3 | Accessibility & i18n final pass | WCAG 2.1 AA, RTL Arabic, French |
| 4 | Documentation & Training | Admin guide, user guide, API reference, training videos |

Phase 5 was the heavy lifting that makes Phase 6 a polish + extension story rather than a "rip up the auth model to add SSO" story.
