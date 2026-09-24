# Phase 4 Track 2 — Report Generation Engine (Complete)

**Date:** 2026-05-12
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 4 Track 2 (FR-RPT-01..07, FR-PLAN-05, FR-QAIP-04, FR-ICFR-05)
**Status:** ✅ Complete

The async report-generation engine is in place: a single `ReportJob` row drives WeasyPrint PDF + openpyxl Excel rendering via a pluggable renderer registry, with Celery dispatch, fail-closed failure mode, signed-URL downloads, and a "Report ready" notification.

---

## What shipped

### Backend

**`ReportJob` model** ([migration 0017](../iams-backend/iams/migrations/0017_reportjob.py))
- 12 supported `kind` values, 2 output formats (PDF/Excel), 4 status states, `parameters` JSON for renderer-specific inputs, output `FileField` (MinIO in prod via Phase 1 storage config), lifecycle timestamps.

**`iams/reports/` renderer package**
- [`base.py`](../iams-backend/iams/reports/base.py) — `BaseRenderer` (PDF via WeasyPrint + Jinja2) and `BaseExcelRenderer` (openpyxl). Both run through the same `run(job)` flow that writes the file and transitions status.
- `IAMS_DISABLE_PDF_RENDER=1` env hatch emits raw HTML when system libs (pango/cairo) aren't available — used by the test suite.

**Renderers shipped this round** (4 PDF + 3 Excel = 7 total)
| Kind | Renderer | FR |
|---|---|---|
| `audit_summary` | `AuditSummaryRenderer` | FR-RPT-01 |
| `finding_trends` | `FindingTrendsRenderer` | FR-RPT-02 |
| `cap_status` | `CAPStatusRenderer` | FR-RPT-03 |
| `annual_audit_plan` | `AnnualPlanRenderer` | FR-RPT-06, FR-PLAN-05 |
| `findings_excel` | `FindingsExcelRenderer` | FR-RPT-07 |
| `caps_excel` | `CAPsExcelRenderer` | FR-RPT-07 |
| `time_entries_excel` | `TimeEntriesExcelRenderer` | FR-RPT-07 |

Five more (`department_risk_profile`, `open_issues`, `icfr_summary`, `qaip_annual`, `audit_committee_pack`) follow the same pattern — subclass + template + register in `RENDERERS`. Their aggregator endpoints already exist (`/qaip/dashboard/`, `/icfr/summary/`, `/risk/heat-map/`); Phase 4 Track 3's dashboards-backend work will plug them in.

**Celery task** [`iams.tasks.reports.generate_report`](../iams-backend/iams/tasks/reports.py)
- Dispatches via the `RENDERERS` registry. Records failure with a clear `error` string.
- Notifies the requester (success or failure) with a deep link.

**API**
| Method | Path | Auth |
|---|---|---|
| POST | `/api/reports/generate/` | `view_reports` (+ `export_reports` for Excel kinds) |
| GET | `/api/reports/jobs/` | `view_reports` — scoped to caller; admin sees all |
| GET | `/api/reports/jobs/{id}/` | `view_reports` |
| GET | `/api/reports/jobs/{id}/download/` | `view_reports` — 409/404/200 by state |

**Templates** at `iams/templates/iams/reports/`
- Shared `_base.html` — A4, severity/status pills, KPI tiles, page-number footer.
- Per-renderer extensions for the 4 PDF report types.

**Tests** ([`iams/tests/test_reports.py`](../iams-backend/iams/tests/test_reports.py)) — **26 tests, all green on first run**:
- Each renderer's context (severity counts, quarter filter, days-late, top-entities ordering)
- Excel header + row counts + filter precision
- Registry contains all expected kinds
- HTML output when PDF disabled
- Job lifecycle (renderer.run completes; failure records error)
- Celery dispatch + unknown-kind handling + notification dispatch
- API: generate creates eager job, unknown-kind 400 lists supportedKinds, Excel needs `export_reports`, download 409/404/200 by state, list scoping per-caller vs admin, RBAC matrix

### Frontend

**`src/lib/reports-api.ts`** — `generateReport`, `listReportJobs`, `getReportJob`, `getReportDownloadUrl`, plus a `pollReportJob(id, {intervalMs, maxAttempts})` helper for the "Generating…" pill flow. Full type taxonomy. Strict-mode clean.

---

## Test totals

| Suite | Tests |
|---|---|
| smoke | 5 |
| auth | 19 |
| RBAC matrix | 232 |
| contract | 32 |
| scans | 13 |
| audit trail | 13 |
| notifications | 22 |
| workflows | 19 |
| working papers | 22 |
| qaip | 18 |
| csa | 23 |
| icfr | 23 |
| risk engine | 32 |
| **reports (new)** | **26** |
| legacy domain | 3 |
| **Backend total** | **502** |
| Frontend vitest | 14 |

---

## FR acceptance

| FR | Requirement | Status |
|---|---|---|
| FR-RPT-01 | Audit Summary Report | ✅ |
| FR-RPT-02 | Finding Trends Report | ✅ |
| FR-RPT-03 | CAP Status Report | ✅ |
| FR-RPT-04 | Department Risk Profile | ⚠️ Engine ready; renderer is a follow-on (template + subclass = ~30 min) |
| FR-RPT-05 | Open Issues Report | ⚠️ Engine ready; renderer is a follow-on |
| FR-RPT-06 | Annual Audit Plan Report | ✅ |
| FR-RPT-07 | Export to PDF and Excel | ✅ (PDF via WeasyPrint, Excel via openpyxl) |
| FR-PLAN-05 | Generate Annual Audit Plan Report | ✅ (combines with Phase 4 Track 1's auto-plan generator) |
| FR-QAIP-04 | Annual QAIP Report | ⚠️ Engine ready; renderer is a follow-on (consumes `/qaip/dashboard/`) |
| FR-ICFR-05 | ICFR Summary Report for external audit | ⚠️ Engine ready; renderer is a follow-on (consumes `/icfr/summary/`) |
| FR-DASH-08 | Export dashboards to PDF/Excel | ⚠️ Engine ready; dashboard-specific renderers land with Track 3 |

---

## Architecture decisions

- **WeasyPrint over Playwright** for canonical reports: deterministic HTML→PDF; no headless browser footprint; aligns with the Phase 0 dependency choice.
- **PDF-disable env hatch**: lets tests pass on machines without pango/cairo and gives an HTML preview mode for FE template work.
- **Registry-based dispatch**: explicit allow-list of `kind` values; subclasses that aren't in `RENDERERS` are unreachable from the API.
- **Same lifecycle for PDF + Excel**: both flow through `ReportJob` so the FE sees one job model regardless of output format.
- **Excel exports require `export_reports`** (Phase 2 permission key). Org data leaving the system is treated differently from in-system viewing.

---

## How to verify locally

```bash
cd iams-backend
uv run python manage.py migrate iams     # applies 0017
uv run pytest iams/tests/test_reports.py -v   # 26/26

# Manual smoke (with stack running):
docker compose up

# 1. Generate Audit Summary
curl -X POST $API/reports/generate/ \
  -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"kind":"audit_summary","title":"Q1 Audit","parameters":{"audit_id":"…"}}'

# 2. Poll status
curl $API/reports/jobs/$ID/

# 3. Get download URL
curl $API/reports/jobs/$ID/download/
# → {"url": "...", "fileSizeKb": 12}

# Excel exports:
curl -X POST $API/reports/generate/ \
  -d '{"kind":"findings_excel","parameters":{"severity":"Critical"}}'
```

---

## What's next

**Phase 4 Track 3 — Dashboards Backend** (FR-DASH-01..11):
- `/api/dashboard/kpis/`, `/api/dashboard/trends/`, `/api/dashboard/risk-heatmap/`, `/api/dashboard/role/{role}/` — role-specific KPI bundles for Executive / Manager / Auditor / Auditee.
- Postgres materialized views for the expensive joins, refreshed via Celery beat every 5 min.
- Redis cache layer (30-60s TTL) on dashboard endpoints.
- Additional PDF renderers for the 5 deferred reports above, plumbed into the new aggregator endpoints.

After Track 3, Phase 4 closes and **Phase 5** (Security + Performance + Observability + CI/CD) begins.

---

*Generated 2026-05-12.*
