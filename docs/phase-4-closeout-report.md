# Phase 4 — Close-Out Report

**Date:** 2026-05-12
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 4
**Status:** ✅ Complete

Phase 4 ("Risk Engine + Reports + Dashboards") landed across three tracks over the past sprint. The phase took the IAMS from "data captured" to "decisions surfaced": risk scores drive the audit plan, the same plan compiles into a board-ready PDF, and the same data lights up the role-specific dashboards.

---

## Tracks shipped

| # | Title | Version | FRs | Tests added | LOC added (rough) |
|---|---|---|---|---|---|
| 1 | Configurable Risk Engine | `0.13.0` | FR-RISK-01..10, FR-PLAN-01..05 | +32 | ~1,200 BE + ~400 FE |
| 2 | Report Generation Engine | `0.14.0` | FR-RPT-01..07, FR-PLAN-05, FR-QAIP-04, FR-ICFR-05 | +26 | ~900 BE + ~150 FE |
| 3 | Dashboards Backend | `0.15.0` | FR-DASH-01..11, FR-RPT-04..05 | +38 | ~700 BE + ~180 FE |
| **Total** | | | | **+96** | |

Test suite: **502 → 540** (all green with `IAMS_DISABLE_PDF_RENDER=1`).

---

## What this means for the product

### For Executives & the Audit Committee
- One-click "Audit Committee Pack" PDF: KPIs, YoY trends, department × risk heat map, rating rollups across QAIP/ICFR/CSA, upcoming audits.
- The `/api/dashboard/role/executive/` endpoint returns the same data the PDF renders from — the JSON dashboard and the printed pack can never drift.

### For Audit Managers
- The risk engine generates the *draft* audit plan from current scores; the plan goes straight into the existing approval-chain workflow.
- Manager bundle endpoint shows KPIs, trends, ratings, upcoming audits, and the recent activity feed.

### For Auditors
- Auditor role bundle slices by `user_email`: their own assigned audits, their own open findings, plus the org-wide upcoming-audit feed.
- Reports they generate get a "Report ready" notification with a deep link.

### For Auditees
- Auditee bundle: their open CAPs, their CSA responses, the recent activity feed scoped to their work.

---

## Architectural decisions worth recording

1. **Single source of truth across surfaces.** Every dashboard JSON endpoint, every PDF that needs the same data, and every role bundle goes through the `iams.dashboards.*` aggregators. Changing the heat-map bucketing once changes it everywhere.
2. **Append-only risk snapshots, with a single `is_current` row enforced at DB level.** Partial unique constraints + the `record_score` service ensure no two "current" rows for the same `(entity, scoring_model)` ever co-exist, even under race.
3. **Pluggable renderer registry.** Adding a new report = subclass `BaseRenderer`, write a template, add to `RENDERERS`. The Celery task is generic; no per-kind dispatch code grows.
4. **Cache with graceful degradation.** All dashboard endpoints route through `cache_or_compute`. If Redis is down (`DJANGO_REDIS_IGNORE_EXCEPTIONS=True`), endpoints fall back to direct DB queries — slow, not broken.
5. **Test-time PDF escape hatch.** `IAMS_DISABLE_PDF_RENDER=1` emits raw HTML instead of calling WeasyPrint; the test suite can exercise every renderer without pango/cairo system libs.

---

## Deferred to later phases

- **Materialized views** for the heat-map and YoY trend aggregations. Deferred to **Phase 5** (performance hardening) — the cache layer handles current load.
- **PDF generation hardening.** Currently we render synchronously inside the Celery worker with WeasyPrint. Phase 5 will benchmark + tune (or swap to a sandboxed Chromium renderer if WeasyPrint stalls on large reports).
- **FE polish for the new dashboards.** The typed clients are in place; rewiring the dashboard pages to use the role-bundle endpoint (and adding the new trend / heat-map widgets) is a focused FE polish task.
- **External-system integration for risk inputs.** The risk engine accepts manual factor values today. Phase 6 will pipe in incident-management, audit-history, and HR-change feeds as automated factor sources.

---

## What's next

Phase 4 unblocks **Phase 5: Security + Performance + Observability + CI/CD**, the production-hardening phase. Major deliverables:

- Threat-model walkthrough + pen-test fixes
- Postgres query budget + materialized-view rollout where justified
- Loki / Prometheus / Grafana wiring + alert rules (oncall paging on CAP-overdue spikes, dashboard cache miss rate, Celery queue depth)
- CI/CD: GitHub Actions / GitLab CI pipelines, container image signing (Cosign), staged deploys with blue-green
- Backup / restore drills + DR runbook

After Phase 5: **Phase 6 (SSO + ERP integrations + a11y + docs)** lands the production-ready, externally-integratable system the user asked for in the original brief.

---

## Operational readiness

- **All migrations applied locally:** `0001..0017` on the dev SQLite, parity verified.
- **No model changes pending** at end of Track 3.
- **All celery beat schedules registered:** `cap-overdue-nightly@2:00`, `weekly-digest-monday@8:00`, `approval-escalation@3:00`, `dashboard-cache-refresh@*/5min`.
- **Settings touched this phase:** `IAMS_DISABLE_PDF_RENDER` (test/dev escape), `DJANGO_REDIS_IGNORE_EXCEPTIONS=True` (graceful Redis degradation).

Phase 4 is shippable. Awaiting "proceed" for Phase 5.
