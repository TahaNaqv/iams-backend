# Phase 4 Track 1 — Configurable Risk Engine (Complete)

**Date:** 2026-05-12
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 4 Track 1 (FR-RISK-01..10)
**Status:** ✅ Complete

The first Phase 4 track. The risk engine is now pluggable: orgs define their own factors, bundle them into named scoring models with one of three formulas, snapshot entity scores into an append-only history with automatic re-ranking, and have the system auto-draft the annual audit plan from the top-N highest-risk entities.

---

## What shipped

### Backend

**Models** ([migration 0016](../iams-backend/iams/migrations/0016_riskfactor_riskscoringmodel_and_more.py)) — four new tables:

| Model | Purpose |
|---|---|
| `RiskFactor` | Catalog of rateable dimensions. `code` + `name`, `scale_min`/`scale_max` (DB check `max > min`). |
| `RiskScoringModel` | Named bundle: `formula` (`weighted_sum` / `weighted_avg` / `multiplicative`), `high_risk_threshold` (Decimal 0..100), partial-unique on `(name)` when `is_active=True`. |
| `RiskFactorWeight` | Through-model; per-model factor weight (unique on `(model, factor)`). |
| `EntityRiskScore` | Append-only per `(entity, scoring_model)`. `is_current` partial-unique. Stores `factor_values` JSON + computed `composite_score` (0..100) + `rank` + `is_high_risk`. |

**Service module** [`iams/risk_engine.py`](../iams-backend/iams/risk_engine.py)
- `compute_composite(model, factor_values)` — formula-aware, range-validated. Three formulas:
  - **weighted_sum**: `Σ ((v - vmin)/(vmax - vmin) · w) / Σ w · 100`
  - **weighted_avg**: `Σ ((v / vmax) · w) / Σ w · 100`
  - **multiplicative**: `(likelihood · impact) / (lmax · imax) · 100` (requires both factors)
- `record_score(entity, model, factor_values, by_user)` — atomic: flips previous current row off, inserts new one, bumps `entity.risk_rating` to High when above threshold (preserves Critical), re-ranks.
- `recompute_ranks(model)` — **dense ranking** across current scores (ties share a rank; next distinct value gets the next consecutive rank).
- `heat_map(model)` — likelihood × impact bucketed grid with per-cell entity lists; requires both factors present in the model.
- `generate_audit_plan_draft(model, year, top_n, requested_by)` — top-N current scores → draft `ApprovalRequest` of type "Audit Plan". The existing Phase 2 chain-template signal auto-applies the configured approval chain (FR-PLAN-01).
- `recompute_all_scores_for_model(model)` — bulk re-snapshot after weight/formula edits.

**API**
| Method | Path | Auth |
|---|---|---|
| CRUD | `/api/risk/factors/` | read: `view_audits`; write: `manage_settings` |
| CRUD | `/api/risk/models/` | read: `view_audits`; write: `manage_settings` |
| CRUD | `/api/risk/factor-weights/` | read: `view_audits`; write: `manage_settings` |
| GET | `/api/risk/scores/` | `view_audits` |
| POST | `/api/risk/scores/record/` | `manage_settings` |
| POST | `/api/risk/models/{id}/recompute/` | `manage_settings` |
| GET | `/api/risk/heat-map/?scoring_model_id=…` | `view_audits` |
| POST | `/api/risk/generate-plan/` | `create_audits` |

Direct POST/PATCH/DELETE on `/api/risk/scores/` returns **405** to force snapshots through the engine. The viewset is read-only externally; mutations go through `/record/`.

**Audit log** captures `risk_score_recorded`, `risk_model_bulk_recompute`, `audit_plan_generated_from_risk` with structured payloads.

**Tests** ([`iams/tests/test_risk_engine.py`](../iams-backend/iams/tests/test_risk_engine.py)) — 32 tests, all green:
- Constraints (scale_min < max, one-active-per-name)
- All three formulas with min/max/mid inputs, weights, missing-factor errors
- Range + numeric validation
- Snapshot flip (current → not_current)
- High-risk threshold + Critical preservation
- Dense ranking with ties
- Heat-map placement + missing-factor error
- Plan generation + empty + top_n validation
- API: record, 400 on bad input, 405 on direct CRUD, heat-map, generate-plan, recompute, RBAC

### Frontend

**`src/lib/risk-engine-api.ts`** — 12 typed async functions + complete taxonomy + DTOs.

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
| **risk engine (new)** | **32** |
| legacy domain | 3 |
| **Backend total** | **476** |
| Frontend vitest | 14 |

---

## FR-RISK-01..10 acceptance

| FR | Requirement | Status |
|---|---|---|
| FR-RISK-01 | Define risk factors | ✅ |
| FR-RISK-02 | Configurable weighted scoring models | ✅ (3 formulas) |
| FR-RISK-03 | Auto-calculate composite risk score | ✅ |
| FR-RISK-04 | Rank entities | ✅ (dense ranking) |
| FR-RISK-05 | Recalc auto-updates audit priority | ✅ (entity risk_rating bump) |
| FR-RISK-06 | Version history of risk assessments | ✅ (append-only snapshots) |
| FR-RISK-07 | Generate risk heat maps | ✅ |
| FR-RISK-08 | Auto-flag high-risk entities | ✅ (`is_high_risk` + risk_rating bump) |
| FR-RISK-09 | Import Enterprise Risk Register (Excel/API) | ⚠️ Partial — existing `RiskAssessmentImportIssue` model exists; bulk-import wizard for the new scoring engine is a follow-up |
| FR-RISK-10 | Map risks to auditable entities | ✅ (`EntityRiskScore.entity` FK) |

FR-PLAN-01 (auto-generate audit plan from top-N risk) also satisfied here.

---

## Deferred to follow-on tracks

- **FR-RISK-09**: bulk-import wizard for risk-register Excel files into the new scoring engine. The existing workbook import wires into `RiskAssessmentRecord`; mapping into `EntityRiskScore` (factor_values per entity) is a focused task.
- **FE Risk Workbook rewiring** — the current page consumes free-text fields; switching it to render computed composites via the typed client lands during FE polish.

---

## How to verify locally

```bash
cd iams-backend
uv run python manage.py migrate iams      # applies 0016
uv run pytest iams/tests/test_risk_engine.py -v   # 32/32

# Manual smoke (with stack running):
docker compose up

# 1. Create factors
curl -X POST $API/risk/factors/ -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"code":"impact","name":"Impact","scaleMin":1,"scaleMax":5,"isActive":true}'
curl -X POST $API/risk/factors/ -H "Authorization: Bearer $T" -H "Content-Type: application/json" \
  -d '{"code":"likelihood","name":"Likelihood","scaleMin":1,"scaleMax":5,"isActive":true}'

# 2. Create scoring model (multiplicative) + weights
curl -X POST $API/risk/models/ -d '{"name":"Default","version":"1.0","formula":"multiplicative","highRiskThreshold":"60","isActive":true}' ...

# 3. Set weights via /risk/factor-weights/ (one row per factor)

# 4. Score an entity
curl -X POST $API/risk/scores/record/ -d '{"entityId":"…","scoringModelId":"…","factorValues":{"likelihood":4,"impact":5}}'

# 5. View heat map
curl $API/risk/heat-map/?scoring_model_id=…

# 6. Generate audit plan draft
curl -X POST $API/risk/generate-plan/ -d '{"scoringModelId":"…","year":2027,"topN":15}'
```

---

## What's next

**Phase 4 Track 2 — Report Generation Engine** (FR-RPT-01..07, FR-PLAN-05, FR-DASH-08, FR-QAIP-04, FR-ICFR-05):
- WeasyPrint PDF templates for: Audit Summary, Finding Trends, CAP Status, Department Risk Profile, Open Issues, Annual Audit Plan, ICFR Summary, QAIP Annual, Audit Committee Pack
- Async generation via Celery; signed-URL download links
- Excel exports via `openpyxl`

After Track 2, **Phase 4 Track 3** (Dashboards Backend — role-specific endpoints + materialized views + Redis cache) closes Phase 4. Then Phase 5 (Security/Perf/Observability/CI-CD).

---

*Generated 2026-05-12.*
