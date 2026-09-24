# Phase 5 Track 2 — Performance & Scale (Complete)

**Date:** 2026-05-13
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 5 Track 2 (NFR-Performance)
**Status:** ✅ Complete

This track delivered the application-side performance work to meet the **500 concurrent users / p95 < 500ms** non-functional requirement. The infra-side pieces (pgbouncer sidecar, nginx static-asset cache tuning) remain operator-owned; the app side is now hardened with right-sized pagination, composite indexes on hot paths, N+1 regression guards, and a repeatable load-test scenario.

---

## What shipped

### 1. Pagination tightening
- `DefaultPagination.page_size` cut from **100 → 25**. List responses are now ~4× lighter by default.
- `max_page_size` ceiling unchanged at 200 — explicit `?page_size=` callers can still ask for bigger.
- The envelope (`count / next / previous / page / pageSize / totalPages / results`) is unchanged.

### 2. Composite indexes ([migration 0019](../iams-backend/iams/migrations/0019_perf_indexes_phase5.py))

| Table | New indexes | Why |
|---|---|---|
| `audit` | `(department, status)`, `(start_date)`, `(lead_auditor)` | `dashboards.upcoming_audits`, role bundles, "my audits" filters |
| `finding` | `(department, status)`, `(owner, status, due_date)`, `(severity, status)`, `(created_date)` | Dashboard heat-map, auditor bundle, finding trends by quarter |
| `correctiveaction` | `(department, status)`, `(owner, status, due_date)`, `(finding, status)` | Overdue-CAP scan, auditee bundle, CAPs-by-finding traversal |

All indexes are additive (no model field changes); migration is forward-only with no data movement and safe to apply during a rolling deploy.

### 3. N+1 fixes
Two endpoints traversed `target_content_type` via `GenericForeignKey` per-row in their serializers; both now `select_related("target_content_type")`:

- `NotificationViewSet` — FE bell polls `/api/notifications/unread-count/` every 60s; the regression would have been per-row ContentType queries.
- `AuditLogViewSet` — same shape.

### 4. Query-budget regression guards
**9 new tests** in `iams/tests/test_performance.py` using Django's `CaptureQueriesContext`:

- **Pagination**: page size defaults to 25, envelope shape stable, `?page_size=500` caps at 200.
- **N+1 budgets**: notifications, audit log, findings, CAPs, audits all bounded ≤ 12 queries on 20–50 row pages.
- **Cache verification**: Dashboard KPIs second call drops to ≤ 8 queries (cache hit).
- **Audit list**: 50-row page bounded ≤ 10 queries.

Budgets are intentionally lax (≈2× current) so harmless future changes don't break them, but tight enough that one new per-row query in a 50-row list explodes the budget.

### 5. Locust load-test scenario
`loadtests/locustfile.py` + `loadtests/README.md`:

- 11 weighted tasks mirroring the real FE polling cadence:
  - Dashboard KPIs + notifications bell at **weight 10**
  - List endpoints at **6 / 4**
  - Role bundles, trends, heat-map at **3 / 2**
  - `/auth/me/` at 1
- Auto-refreshes tokens on 401.
- Headless run targets `500 concurrent users / 25-user ramp / 5m duration` with HTML report output.

---

## Tests

**573 / 573 passing** (was 564; +9 new performance tests).

| Test | Budget | Current |
|---|---:|---:|
| `notifications_list_is_not_n_plus_one` (20 rows) | ≤ 12 | ~6 |
| `audit_log_list_is_not_n_plus_one` (20 rows) | ≤ 12 | ~6 |
| `findings_list_is_not_n_plus_one` (50 rows) | ≤ 12 | ~7 |
| `caps_list_is_not_n_plus_one` (50 rows) | ≤ 12 | ~7 |
| `audits_list_query_budget` (50 rows) | ≤ 10 | ~6 |
| `dashboard_kpis_query_budget` (cold) | ≤ 12 | ~9 |
| `dashboard_kpis_query_budget` (cached) | ≤ 8 | ~4 |

---

## Decisions

- **`CaptureQueriesContext` over `nplusone` runtime detection.** `nplusone` is great in dev — but it monkey-patches Django and emits warnings; a failed assertion in CI is more legible than parsing log noise, and the budgets are explicit numbers we can grep for.
- **Composite indexes targeted at dashboard aggregators.** Indexes have cost (write overhead, planner table churn). We added them on the specific 2-3 column combinations the dashboard aggregators and role bundles actually use, not on every `status` and FK on every model.
- **Page size = 25 across the board.** Most FE list views render ≤ 25 rows above the fold; the new default eliminates the gap between "what's rendered" and "what's transferred." Dense pages (large CSV-like exports) ask for `?page_size=` explicitly.
- **Locust scenario weights = FE polling cadence.** The point of load testing is to stress what users actually do. The 10/10/6/6/4 weight ladder reproduces a typical workday: heavy dashboard + notifications polling, occasional drill-downs, infrequent admin views.

---

## What's deferred to infra

These pieces require operator action (not code):

- **pgbouncer sidecar** in docker-compose / k8s for Postgres connection pooling.
- **nginx static cache** with long `Cache-Control: public, max-age=…, immutable` headers on hashed assets.
- **`EXPLAIN ANALYZE` on the 10 slowest endpoints** against a production-shaped dataset — needs the staging env that the load test runs against.

---

## What's next in Phase 5

| Track | Title | Status |
|---|---|---|
| 1 | Security | ✅ Complete |
| 2 | **Performance & Scale** | ✅ Complete |
| 3 | Observability | ⏳ Next |
| 4 | CI/CD | ⏳ |
