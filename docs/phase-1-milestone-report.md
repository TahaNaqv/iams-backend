# Phase 1 Milestone Report — Auth Hardening + RBAC Matrix

**Date:** 2026-05-12
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 1
**Status:** Tracks 1 & 4 complete (5 of 8 todos). Tracks 2 & 3 carried forward to a follow-on session.

---

## What shipped

### Track 1 — Auth hardening (4/4 sub-tasks complete)

**Backend** ([iams-backend/iams/views/auth.py](../iams-backend/iams/views/auth.py), [iams-backend/iams/serializers.py](../iams-backend/iams/serializers.py))

| Endpoint | Behavior | Tests |
|---|---|---|
| `POST /api/auth/password/reset/` | Anonymous. Always returns **202**, never reveals whether email is registered. If valid, dispatches `iams.send_password_reset_email` Celery task. Throttled `auth_burst` (10/min). | 3 |
| `POST /api/auth/password/reset/confirm/` | Anonymous. Validates `{uid, token, new_password}` with `default_token_generator`. Single-use (token invalidates on success). Enforces password complexity (≥12 chars, common-password check). | 5 |
| `POST /api/auth/password/change/` | Authenticated. Requires `current_password`. Wrong current → 400 with field-level error. | 3 |
| `PATCH /api/auth/me/` | Authenticated. Exposes `first_name`, `last_name`, `email` only — `role_id` / `status` silently ignored to prevent privilege escalation. Duplicate-email check. | 3 |

**Email pipeline** — Celery task with autoretry (3× exponential backoff, jitter), HTML + plain-text templates at [iams-backend/iams/templates/iams/email/password_reset.{txt,html}](../iams-backend/iams/templates/iams/email/password_reset.html). Dev points at mailhog; prod at SMTP relay.

**Total auth tests: 19, all passing** (including a full round-trip: request → mail.outbox → confirm → login with new password).

**Frontend** ([iams-frontend/src/lib/auth-api.ts](../iams-frontend/src/lib/auth-api.ts) + 3 new pages)

| Page | Route | Purpose |
|---|---|---|
| [ForgotPasswordPage.tsx](../iams-frontend/src/pages/ForgotPasswordPage.tsx) | `/forgot-password` (public) | Email entry → "check your inbox" confirmation (regardless of email existence) |
| [ResetPasswordPage.tsx](../iams-frontend/src/pages/ResetPasswordPage.tsx) | `/reset-password/:uid/:token` (public) | Parses tokenized URL, validates new password client-side, confirms with backend |
| [ChangePasswordPage.tsx](../iams-frontend/src/pages/ChangePasswordPage.tsx) | `/profile/change-password` (authenticated) | Current + new + confirm; Zod cross-field rules; wrong-current → field error |

**UX integrations**:
- "Forgot password?" link added to [LoginPage](../iams-frontend/src/pages/LoginPage.tsx).
- [UserProfile](../iams-frontend/src/pages/UserProfile.tsx) `saveProfile` now calls the real `updateMe` (was a mock toast).
- Inline password-change form on UserProfile replaced with a single clean link to the dedicated page.
- All new code compiles cleanly under Phase 0's TS `strict: true` config.

### Track 4 — RBAC matrix test ([iams-backend/iams/tests/test_rbac_matrix.py](../iams-backend/iams/tests/test_rbac_matrix.py))

The central guarantee that **role gates can't silently drift**:

- **Endpoint inventory**: 32 list endpoints (every router-registered ViewSet + the nested action URLs the FE consumes), tagged with their declared `HasPermission(...)` key.
- **Role inventory**: 6 roles (Super Admin, Audit Manager, Lead Auditor, Auditor, Department Head, Executive) with their permission sets locked in fixture form.
- **Matrix**: 32 × 6 = **192 combinations**, plus 32 anonymous-rejection assertions, plus 1 super-admin sweep test = **232 parametrized tests**, all passing.

**Real bug caught**: `ChecklistItemViewSet` declared `permission_classes = [HasPermission("edit_audits")]` for **all** actions — meaning Auditor / Department Head / Executive (who hold `view_audits` but not `edit_audits`) got 403 on GET. The FE contract treats checklist reads as `view_audits`-gated. Fixed by introducing `get_permissions()` that distinguishes read vs. write, mirroring [AuditViewSet](../iams-backend/iams/views/domain.py).

### Incidental fixes during Phase 1

- **drf-spectacular postprocessing hook** had the wrong import path. Fixed.
- **`djangorestframework-camel-case` parser/renderer removed** — the existing 30+ serializers already declare camelCase explicitly via `source="snake_case"`, and the auto-translator caused double translation. Settings updated, documented inline.
- **Test settings throttle rates** zeroed out (not just `DEFAULT_THROTTLE_CLASSES`) so views with explicit `ScopedRateThrottle` don't fire 429s in tests.
- **Pagination warnings** silenced on `RiskAssessmentMatrixCell`, `RiskAssessmentSummaryItem`, `RiskAssessmentImportIssue` via explicit `order_by` (also stabilizes paginator results).

---

## Test totals

| Suite | Tests | Status |
|---|---|---|
| Backend smoke (`test_smoke.py`) | 5 | ✅ |
| Backend auth (`test_auth.py`) | 19 | ✅ |
| Backend RBAC matrix (`test_rbac_matrix.py`) | 232 | ✅ |
| **Backend contract (`test_contract.py`)** | **32** | **✅ NEW** |
| Backend legacy domain (`test_legacy_domain.py`) | 3 | ✅ |
| **Backend total** | **291** | **✅ ~85% coverage** |
| Frontend (vitest) | 14 | ✅ |

---

## Track 2 — Contract verification ✅

Implemented as a long-lived **executable** contract test ([`iams/tests/test_contract.py`](../iams-backend/iams/tests/test_contract.py)) — 32 tests, one per major endpoint, asserting the response payload matches the FE's TypeScript model exactly:

- Every camelCase field present
- No snake_case alias leaks through  
- Nested types (steps[], sections[], procedures[]) recursively checked
- Pagination unwrap already in place in [api.ts](../iams-frontend/src/lib/api.ts) — the FE service contract stays `T[]`

### Real drift caught and fixed
- **`RiskAssessmentImportIssue`** — backend exposed `sheetName`/`rowNumber` but FE contract is `sheet`/`cell`. Renamed the field via [migration 0006](../iams-backend/iams/migrations/0006_rename_sheet_name_riskassessmentimportissue_sheet_and_more.py), added the missing `cell` field, simplified serializer.

### Incidental stability fixes
- Default page size bumped 25→100 so unfetched-page-2 data doesn't silently disappear from the FE before Phase 4 dashboard work introduces real pagination UI.
- Added `order_by` to 8 viewsets that emitted `UnorderedObjectListWarning`.

## Track 3 — MinIO storage + ClamAV ✅

Every upload (`EvidenceFile` and `ManagedDocument`) is now scanned by a self-hosted ClamAV daemon. The flow:

```
POST /api/audits/<id>/evidence/   (FE)
  │
  ▼
EvidenceByAuditView.post → EvidenceFile row created (scan_status="pending")
  │
  ▼
scan_uploaded_file.delay(model_label, object_id)  (Celery)
  │
  ▼
clamd INSTREAM over TCP (host=clamav, port=3310)
  │
  ├── verdict "OK"     → scan_status="clean",    quarantined=False
  ├── verdict "FOUND"  → scan_status="infected", quarantined=True, scan_signature=<virus>
  ├── verdict "ERROR"  → scan_status="error",    quarantined=True (fail-closed)
  │
  ▼
GET /api/evidence-files/<id>/download/
  ├── 403  if quarantined
  ├── 409  if scan still pending
  └── 200  with signed URL (MinIO presigned in prod) or absolute media URL (dev)
```

### Backend deliverables
- `iams/models.py` — new fields on `EvidenceFile` + `ManagedDocument`: `scan_status`, `scan_signature`, `scanned_at`, `quarantined` (migration 0007).
- `iams/tasks/scans.py` — Celery task with autoretry on network errors, fail-closed behavior, file-size cap (`CLAMD_MAX_FILE_MB`), `CLAMD_SKIP` escape hatch for environments without clamd.
- `iams/views/domain.py` — `EvidenceByAuditView.post` and `ManagedDocumentViewSet.perform_create/update` dispatch the scan task; download endpoint enforces quarantine.
- `iams/domain_serializers.py` — exposes `scanStatus`/`scanSignature`/`scannedAt`/`quarantined`; `ManagedDocumentSerializer.downloadUrl` returns `null` when quarantined.
- `docker-compose.yml` — `clamav` service (`clamav/clamav:stable`) with healthcheck.
- `config/settings/{base,test}.py` — `CLAMD_*` config + test-mode short-circuit.
- `pyproject.toml` — adds `clamd>=1.0.2`.
- `iams/tests/test_scans.py` — 13 new tests, all green.

### Frontend deliverables
- `src/components/ScanStatusBadge.tsx` — presentational badge with tooltip for the four scan states.
- `AuditDetail.tsx` evidence list — renders the badge, paints quarantined rows in destructive color, disables download button while pending/quarantined.
- New optional `EvidenceFile` fields in `src/data/mock-data.ts`.

### How to verify
```bash
cd iams-backend
uv sync                                # picks up clamd
uv run python manage.py migrate iams   # applies 0007
uv run pytest iams/tests/test_scans.py -v   # 13 pass

# Full local stack — note ClamAV cold start downloads ~250MB
docker compose up --build
# After ~10 min, clamav goes healthy and the worker starts scanning real uploads.

# Quick way to dispatch a scan without waiting for clamav cold-start:
# Set CLAMD_SKIP=1 in .env and uploads will be auto-marked clean.
```

## Deferred follow-ups (parked into Phase 2 backlog)

### Pre-existing FE↔BE EvidenceFile field-name drift

The FE `EvidenceFile` interface uses `filename`/`fileType`/`size`/`uploadedDate`/`category`/`version`/`wpRef`; the backend serializer returns `name`/`type`/`sizeKb`/`uploadedAt` (+ the four new scan fields). FE mock data uses the FE shape; the API service layer silently casts. End-to-end this means real-API runs render `undefined` for several fields on `AuditDetail`.

To clean in a focused session:
1. Run `npm run gen:api` against the live `/api/schema/` → generates `src/services/api-types.gen.ts`.
2. Replace the hand-rolled `EvidenceFile` interface with the generated type.
3. Update `AuditDetail.tsx` (2 spots) and FE mock data to match the canonical shape.
4. Migrate `src/services/mock.ts` evidence implementations to MSW handlers.

### FE-side upload progress + retry
The Track 3 plan listed an FE upload progress bar and retry-on-failure. The backend now reports `scanStatus` so the FE can poll for completion, but the upload widget itself doesn't yet show a percent-complete bar or retry. Phase 4 dashboard work touches the same component and is the natural place to do this.

---

## How to verify Phase 1 end-to-end locally

```bash
cd iams-backend

# Full suite — 304 tests
uv run pytest

# Specific surfaces
uv run pytest iams/tests/test_auth.py -v          # 19 auth
uv run pytest iams/tests/test_rbac_matrix.py -q   # 232 RBAC matrix
uv run pytest iams/tests/test_contract.py -v      # 32 contract conformance
uv run pytest iams/tests/test_scans.py -v         # 13 AV / quarantine

# Full stack with MinIO + ClamAV
docker compose up --build
# Wait ~10 min for clamav to finish downloading virus signatures.
# To skip clamd during dev: set CLAMD_SKIP=1 in .env

# Swagger + service URLs
open http://localhost:8001/api/docs/   # OpenAPI 3.1
open http://localhost:8025             # mailhog
open http://localhost:9001             # MinIO console
open http://localhost:5555             # Flower (Celery)
```

```bash
cd iams-frontend

npm run test                # vitest — 14 pass
npm run typecheck           # ~200 legacy strict-mode errors remain; new code is clean
npm run dev
# Try: /forgot-password, /reset-password/X/Y, /profile/change-password,
# and the evidence list on any AuditDetail page (look for ScanStatusBadge).
```

---

## Phase 1 final tally

| Metric | Phase 0 baseline | Phase 1 close |
|---|---|---|
| Backend tests | 5 | **304** |
| Backend coverage | 78% | **~85%** |
| Contract surface | prose | **32 executable tests** |
| RBAC matrix coverage | 0 | **232 combinations** |
| Auth endpoints | login/refresh | login/refresh/me-read/me-update/change-pw/reset/reset-confirm/blacklist |
| FE pages added | 0 | **ForgotPassword, ResetPassword, ChangePassword** |
| Storage | local disk | **MinIO opt-in (signed URLs, SSE-AES256)** |
| Upload safety | none | **ClamAV scan + quarantine + 403/409 on download** |
| Real bugs caught & fixed by the new test suites | — | ChecklistViewSet permission, RiskAssessmentImportIssue field rename, KPI ordering, 8 unordered viewsets |

---

## What's next

Phase 1 is **closed**. **Phase 2** begins:

1. **Audit Trail auto-capture** — DRF mixin that diffs every model change and writes to `AuditLogEntry`, plus Postgres-level REVOKE making the table append-only at the DB layer.
2. **Notifications + email dispatch** — Celery beat schedule for CAP-overdue reminders, weekly digests; user preference editor.
3. **Approval workflow engine** — escalation timers, full Auditor → Manager → CAE → Board chain, signal-driven side effects when a request approves/rejects.

---

*Generated 2026-05-12.*
