# Phase 3 Track 2 — QAIP (Complete)

**Date:** 2026-05-12
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 3 Track 2 (FR-QAIP-01..06)
**Status:** ✅ Complete

The second of four Phase 3 modules. The Quality Assurance & Improvement Program — the audit function auditing itself — is now first-class with four resource families and an aggregate dashboard endpoint.

---

## What shipped

### Backend

**Four new models** ([migration 0013](../iams-backend/iams/migrations/0013_auditkpi_qaipassessment_qaipfinding_and_more.py)):

- **`QAIPAssessment`** — internal / external / peer / post-engagement reviews of the IA function. Status (planned/in_progress/completed), overall rating (satisfactory/needs_improvement/unsatisfactory), lead reviewer FK, scope, methodology, summary, period.
- **`QAIPFinding`** — *distinct* from regular `Finding`. Raised against the audit function itself: working-paper quality, methodology gaps, documentation inconsistency, etc. Severity, owner (text + optional FK), recommendation, due date.
- **`StakeholderSurvey`** — satisfaction (1-5) with **DB-level check constraint**, audit FK, role taxonomy (auditee / dept head / executive / board / audit committee / external auditor / other), **anonymous** flag that scrubs `respondent` on save and defensively on serialise.
- **`AuditKPI`** — `(kpi_type, period)` unique. Target vs actual decimals, direction (higher_is_better / lower_is_better), computed `variance` + `favorable` properties.

**API**
| Resource | Endpoint | Filters |
|---|---|---|
| Assessments | `/api/qaip/assessments/` | `?type=` `?period=` `?status=` |
| Findings | `/api/qaip/findings/` | `?assessment_id=` `?status=` |
| Surveys | `/api/qaip/surveys/` | `?audit_id=` `?respondent_role=` |
| KPIs | `/api/qaip/kpis/` | `?kpi_type=` `?period=` |
| **Dashboard** | `/api/qaip/dashboard/` | `?period=` |

Dashboard returns: `assessmentsByType`, `assessmentsByStatus`, `openQaipFindings`, `criticalQaipFindings`, `avgSatisfaction`, `surveyResponseCount`, `kpis` (latest period when no filter).

**RBAC** — `view_reports` gates read+write across all five endpoints (matches existing `AuditReportViewSet` pattern).

**Audit trail** — every QAIP write flows through `AuditedViewSetMixin` so the existing audit-log capture picks up the change automatically.

**Tests** ([`iams/tests/test_qaip.py`](../iams-backend/iams/tests/test_qaip.py)) — 18 tests:
- Assessment list with camelCase + filters
- Finding nested counts via prefetch
- Finding create + filter by assessment
- Survey anonymity scrubbing on save AND on serialise (defensive against legacy imports)
- DB check constraint blocks satisfaction_score outside 1-5
- Serializer-level range check fires before the DB
- Survey filter by audit + role
- KPI variance higher-is-better + lower-is-better + zero-variance favorable
- KPI uniqueness on (kpi_type, period)
- KPI API emits variance + favorable
- Dashboard aggregates assessments / findings / surveys / KPIs correctly
- Dashboard respects `?period=` filter
- RBAC: all five endpoints return 403 without `view_reports`

### Frontend

**`src/lib/qaip-api.ts`** — typed client for the full surface. Includes:
- The complete type taxonomy (`QAIPAssessmentType`, `QAIPFindingRating`, `SurveyRespondentRole`, `AuditKPIKind`, …) mirroring backend constants exactly.
- DTOs for all four resources + the aggregate dashboard.
- `listAssessments`, `getAssessment`, `createAssessment`, `listQAIPFindings`, `listSurveys`, `submitSurvey`, `listKPIs`, `getQaipDashboard`.

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
| **qaip (new)** | **18** |
| legacy domain | 3 |
| **Backend total** | **398** |
| Frontend vitest | 14 |

---

## FR-QAIP-01..06 acceptance

| FR | Requirement | Status |
|---|---|---|
| FR-QAIP-01 | Record internal quality assessments | ✅ |
| FR-QAIP-02 | Record external quality reviews | ✅ |
| FR-QAIP-03 | Capture stakeholder satisfaction surveys | ✅ (with anonymity + DB-enforced 1-5) |
| FR-QAIP-04 | Generate annual QAIP report | ⚠️ Data + dashboard ready; PDF generation deferred to Phase 4 Track 2 (WeasyPrint) |
| FR-QAIP-05 | Track audit KPIs (timeliness, review quality) | ✅ |
| FR-QAIP-06 | Support peer reviews and post-engagement evaluations | ✅ (via `peer` and `post_engagement` assessment types) |

---

## Deferred to Phase 4 Track 2 (Report Generation Engine)
- **Annual QAIP Report PDF** — the dashboard endpoint already returns the canonical aggregate; the WeasyPrint template will consume it.

## Deferred to FE polish session
- **QAIP Dashboard page** — satisfaction trend chart, KPI vs target bar chart with green/red variance, open-findings-by-rating tile, recent surveys list. Typed client is ready.
- **Stakeholder survey form** — embedded on AuditDetail after audit closes; uses `submitSurvey()` from the typed client.

---

## How to verify locally

```bash
cd iams-backend
uv run python manage.py migrate iams                # applies 0013
uv run pytest iams/tests/test_qaip.py -v            # 18/18

# Manual smoke (with the stack running):
docker compose up
# 1. POST /api/qaip/assessments/ with type=internal + period=2026
# 2. POST /api/qaip/findings/ pointing at the assessment, rating=high
# 3. POST /api/qaip/surveys/ with auditId, respondentRole=auditee, satisfactionScore=4
# 4. POST /api/qaip/kpis/ kpi_type=coverage, period=2026-Q1, target=80, actual=85
# 5. GET /api/qaip/dashboard/ → aggregated payload
```

---

## What's next

**Phase 3 Track 3 — CSA** (Control Self-Assessment, FR-CSA-01..05):
- `CSAQuestionnaire`, `CSAQuestion`, `CSAResponse`, `CSAAnswer` models
- Questionnaire designer + responder + auditor challenge workflow
- Auto-flag entities with low scores for next year's risk-based audit plan

After Track 3, Track 4 (ICFR — financial-control design + operating testing, deficiency reporting) closes out Phase 3.

---

*Generated 2026-05-12.*
