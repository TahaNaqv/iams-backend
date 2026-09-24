# Phase 4 Track 3 — Dashboards Backend (Complete)

**Date:** 2026-05-12
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 4 Track 3 (FR-DASH-01..11, FR-RPT-04..05, FR-ICFR-05, FR-QAIP-04)
**Status:** ✅ Complete

This track finishes Phase 4 by closing out the dashboards backend: a small set of pure aggregator functions, a thin caching layer in front of them, six new endpoints, the five deferred PDF reports, and a typed FE client. The same primitives feed every surface — the dashboard JSON, the audit-committee PDF, and the role bundles — so numbers stay consistent across the app.

---

## What shipped

### Backend

**`iams/dashboards.py` service module**
- Pure aggregator functions, all JSON-serializable, all cacheable:
  - `core_kpis(period?, department?)` — the four KPI cards.
  - `trends(period="YoY"|"FY{N}", department?)` — 8-quarter rolling or 4-quarter FY series.
  - `risk_heatmap_by_department()` — bucketed `EntityRiskScore` counts.
  - `rating_summary(period?)` — QAIP / ICFR / CSA rollup.
  - `recent_activity(limit)` — last N audit-log rows (uncached, live).
  - `upcoming_audits(limit, department?)` — future-dated audits.
  - `role_bundle(role, user_email?)` — pre-composed panels per role.
- Cache helper: `cache_or_compute(key, fn, ttl=45s)` with sha256-hashed kwargs as the key suffix; `invalidate_dashboard_cache()` flushes the namespace.

**New API endpoints** (all under `/api/dashboard/`)
| Path | View | Cache | RBAC |
|---|---|---|---|
| `GET /kpis/` | `DashboardKPIView` (refactored) | 45s | `IsAuthenticated` |
| `GET /trends/` | `DashboardTrendsView` | 45s | `view_reports` |
| `GET /risk-heatmap/` | `DashboardRiskHeatmapByDepartmentView` | 45s | `view_reports` |
| `GET /ratings/` | `DashboardRatingSummaryView` | 45s | `view_reports` |
| `GET /activity/` | `DashboardActivityView` | none | `IsAuthenticated` |
| `GET /upcoming-audits/` | `DashboardUpcomingAuditsView` | 45s | `view_audits` |
| `GET /role/<role>/` | `DashboardRoleView` | 45s (per-user for auditor/auditee) | `IsAuthenticated` |

**Celery beat** — `dashboard-cache-refresh` runs `iams.dashboards.refresh_caches` on `crontab(minute="*/5")`. The task flushes the cache namespace and warms `core_kpis`, `trends(YoY)`, `risk_heatmap_by_department`, and `rating_summary` so the next FE poll lands on a hot key.

**Five additional PDF renderers** (all registered in `iams.reports.RENDERERS`)
| Kind | Renderer | FR | Consumes |
|---|---|---|---|
| `department_risk_profile` | `DepartmentRiskProfileRenderer` | FR-RPT-04 | `dashboards.risk_heatmap_by_department` |
| `open_issues` | `OpenIssuesRenderer` | FR-RPT-05 | direct `Finding` + `CorrectiveAction` queries |
| `icfr_summary` | `ICFRSummaryRenderer` | FR-ICFR-05 | `iams.icfr.build_icfr_summary` |
| `qaip_annual` | `QAIPAnnualRenderer` | FR-QAIP-04 | direct QAIP queries + KPI rollup |
| `audit_committee_pack` | `AuditCommitteePackRenderer` | FR-DASH-11 | every dashboard aggregator |

Templates live under `iams/templates/iams/reports/` and extend the shared `_base.html` — page-numbered footer, A4 layout, severity/status pills, KPI tiles all inherited.

### Frontend

**`src/lib/dashboards-api.ts`** — strict-mode-clean typed client. The notable bit is the discriminated-union `RoleBundle`:

```ts
type RoleBundle = ExecutiveBundle | ManagerBundle | AuditorBundle | AuditeeBundle;
```

The FE can `switch (bundle.role)` and the compiler narrows the payload shape — no manual casting, no `any`, no runtime checks on bundle shape.

### Tests

**38 new tests** in `iams/tests/test_dashboards.py`:
- Aggregator math, including period and department filters (12)
- Role-bundle composition + auditor/auditee user-scoping (4)
- Cache hit-vs-miss instrumentation + invalidate behavior (2)
- Every new API endpoint, including the 400 path for unknown role (9)
- Every new renderer's context + filter behavior (8)
- Registry coverage + IAMS_DISABLE_PDF_RENDER round-trip (3)

---

## Test count

| Phase | Tests |
|---|---|
| Phase 0 | 5 |
| Phase 1 | +27 (32) |
| Phase 1 (RBAC + scans + audit-trail) | +258 (290) |
| Phase 2 (notifications + workflows + working papers) | +63 (353) |
| Phase 3 (QAIP + CSA + ICFR) | +64 (417) |
| Phase 4 Track 1 (risk engine) | +32 (449) |
| Phase 4 Track 2 (reports) | +26 (475)¹ |
| **Phase 4 Track 3 (dashboards)** | **+38 (540)** |

¹ Test count grew from 475 → 502 across Phase 4 Track 2 stabilization fixes; this track adds 38 to land at 540.

All 540 tests pass with `IAMS_DISABLE_PDF_RENDER=1` set.

---

## Decisions & notes

- **Why 45 s TTL, not 30 or 60.** FE polls at 60 s. 45 s gives at most one near-instant cache hit between polls; lower values waste compute, higher values risk stale data when an auditor closes a CAP and refreshes.
- **Why hash the cache key.** Period + department filters compose into a small key space, but caching by raw string would let users smuggle unusual values into the key. Hashing keeps keys compact and prevents accidental pattern-matching pitfalls.
- **Materialized views deferred.** The current cache layer handles the expected load (≈60 s polls × 4 roles × ~20 concurrent users) comfortably. Phase 5 will materialize the trend + heat-map aggregations if production usage justifies it.
- **`recent_activity` is uncached.** The activity feed is a live signal — caching it would make it lag the actions an auditor just took. The endpoint is cheap (one query, indexed, capped LIMIT).
- **Role-bundle cache keys include `user_email` for auditor/auditee.** Without that, two auditors would share a cached payload listing only one of their findings. Executive / manager bundles don't slice by user, so they share the same key.

---

## Phase 4 — close-out

Phase 4 is complete. The three tracks together:

- **Track 1: Risk Engine** (`0.13.0`) — configurable, formula-aware risk scoring with append-only snapshots and audit-plan generation.
- **Track 2: Report Generation Engine** (`0.14.0`) — 7-renderer registry, async Celery dispatch, Excel + PDF, signed-URL downloads.
- **Track 3: Dashboards Backend** (`0.15.0`) — aggregator service + cache layer + 6 endpoints + 5 additional PDFs that consume the same primitives.

See [`phase-4-closeout-report.md`](phase-4-closeout-report.md) for the cross-track summary.
