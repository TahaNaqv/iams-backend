# Phase 3 Track 3 — Control Self-Assessment (CSA) (Complete)

**Date:** 2026-05-12
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 3 Track 3 (FR-CSA-01..05)
**Status:** ✅ Complete

The third of four Phase 3 modules. Business units can now self-evaluate their controls against IA-authored questionnaires. The system auto-scores submissions, flags weak units (auto-bumping their `risk_rating` for the risk engine to pick up next year), and supports an end-to-end auditor challenge workflow.

---

## What shipped

### Backend

**Models** ([migration 0014](../iams-backend/iams/migrations/0014_csaanswer_csaquestion_csaquestionnaire_csaresponse.py)) — four new tables:

| Model | Purpose |
|---|---|
| `CSAQuestionnaire` | IA-authored template. Framework, version, status, configurable `weak_threshold` (default 60). Unique on `(title, version)`. |
| `CSAQuestion` | One row per question. Four response types (`yes_no`, `scale_1_5`, `text`, `evidence_required`), optional `category` (design / operating), `weight`, `order`. |
| `CSAResponse` | One business unit's submission. Status (draft / submitted / under_review / closed), `score_overall`, `score_design`, `score_operating`, `is_weak`. |
| `CSAAnswer` | One per `(response, question)` (unique). Carries `value`, optional `evidence_file` FK, embedded auditor-challenge thread. |

**Service module** [`iams/csa.py`](../iams-backend/iams/csa.py)
- `compute_scores(response)` — overall + per-category 0-100 score from weight-scaled answer fractions:
  - `yes_no`: yes → 1.0, else 0.0
  - `scale_1_5`: linear `(n-1)/4`
  - `text`: non-empty → 1.0
  - `evidence_required`: non-empty value AND `evidence_file` non-null → 1.0
- `submit_response(response, by_user)` — atomic: refuses non-draft / inactive questionnaire / empty answers. Locks the response, computes scores, fires weak-control side effects when below threshold.
- `open_challenge(answer, by_user, note)` — auditor opens a challenge; parent → `under_review`.
- `resolve_challenge(answer, by_user, note)` — auto-rolls parent back to `submitted` when no challenges remain.
- `close_response(response, by_user)` — auditor closes; refuses while challenges open.

**Weak-control side effects** (FR-CSA-04)
- `dispatch_to_role("Audit Manager", kind=KIND_GENERIC, level=WARNING, link="/csa")` — every Audit Manager gets an in-app + email notification.
- Best-effort bump of `AuditableEntity.risk_rating` to `High` (preserves `Critical`).
- Both side effects are exception-swallowed so a notification failure can't roll back the submit.

**API**
| Method | Path | Auth |
|---|---|---|
| GET / POST / PATCH / DELETE | `/api/csa/questionnaires/` | read: `view_audits`; write: `manage_settings` |
| GET / POST / PATCH / DELETE | `/api/csa/questions/` | read: `view_audits`; write: `manage_settings` |
| GET / POST / PATCH / DELETE | `/api/csa/responses/` | `IsAuthenticated`; `?weak=true` filter |
| GET / POST / PATCH / DELETE | `/api/csa/answers/` | `IsAuthenticated` |
| POST | `/api/csa/responses/{id}/submit/` | `IsAuthenticated` (service-layer auth) |
| POST | `/api/csa/responses/{id}/close/` | `IsAuthenticated` |
| POST | `/api/csa/answers/{id}/challenge/` | `IsAuthenticated` |
| POST | `/api/csa/answers/{id}/resolve/` | `IsAuthenticated` |

**Audit-log integration** — every domain action (submit, challenge, resolve, close) records an `AuditLogEntry` with the structured event payload + score / weak flag.

**Tests** ([`iams/tests/test_csa.py`](../iams-backend/iams/tests/test_csa.py)) — 23 tests:
- Scoring math: all-max, no-answers, per-category split, scale_1_5 linear mapping, evidence_required without file
- Submit: locks + scores + fail-on-already-submitted, fail-on-inactive-questionnaire, fail-on-empty-response
- Weak-control: notification dispatch, entity risk bump, Critical preservation
- Challenge: open requires note, can't challenge draft, resolve clears under_review when last
- Close: blocked while challenges open, succeeds after resolution
- API: submit endpoint records audit log, challenge → resolve flow, questionnaire write requires manage_settings, `?weak=true` filter

### Frontend

**`src/lib/csa-api.ts`** — full typed client (14 async functions) + complete type taxonomy mirroring backend constants.

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
| **csa (new)** | **23** |
| legacy domain | 3 |
| **Backend total** | **421** |
| Frontend vitest | 14 |

---

## FR-CSA-01..05 acceptance

| FR | Requirement | Status |
|---|---|---|
| FR-CSA-01 | Allow creation of CSA questionnaires | ✅ |
| FR-CSA-02 | Allow business units to submit responses | ✅ |
| FR-CSA-03 | Auto-score control design AND operating effectiveness | ✅ (via `category` field on questions + per-category score) |
| FR-CSA-04 | Auto-flag weak control units for audit prioritization | ✅ (notification + `risk_rating` bump + `is_weak` flag for filtering) |
| FR-CSA-05 | Support auditor review and challenge workflow | ✅ (open/resolve/close lifecycle on individual answers) |

---

## Deferred to FE polish session
- **CSA Designer page** — drag-and-drop question builder. Typed client + create endpoints are ready.
- **CSA Responder Form** — type-aware inputs (toggle for yes/no, slider for 1-5, textarea for text, file picker for evidence_required). The endpoint already returns the question taxonomy.
- **CSA Auditor Review page** — list of submitted responses, click into challenges, threaded notes. All actions exposed in `csa-api.ts`.

---

## How to verify locally

```bash
cd iams-backend
uv run python manage.py migrate iams       # applies 0014
uv run pytest iams/tests/test_csa.py -v    # 23/23

# Manual smoke (with the stack running):
docker compose up
# 1. POST /api/csa/questionnaires/ with status=active, weakThreshold=60
# 2. POST /api/csa/questions/ × N
# 3. POST /api/csa/responses/ as a business-unit user
# 4. POST /api/csa/answers/ for each question
# 5. POST /api/csa/responses/{id}/submit/ → auto-score + weak check
# 6. (if weak) Audit Manager sees notification at the bell
# 7. As Audit Manager: POST /api/csa/answers/{id}/challenge/ {"note":"..."}
# 8. Responder: POST /api/csa/answers/{id}/resolve/ {"note":"..."}
# 9. Audit Manager: POST /api/csa/responses/{id}/close/
```

---

## What's next

**Phase 3 Track 4 — ICFR** (Internal Control over Financial Reporting, FR-ICFR-01..05):
- `Control`, `ControlTest`, `ControlException`, `DeficiencyReport` models
- Test-of-design + test-of-operating-effectiveness flows
- Deficiency classification (control_deficiency / significant / material_weakness)
- ICFR Summary export for external auditors

Track 4 closes out Phase 3 and unlocks Phase 4 (reports + risk engine + dashboards).

---

*Generated 2026-05-12.*
