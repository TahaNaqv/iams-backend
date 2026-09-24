# Phase 3 Track 1 — Working Papers + sign-off + versioning (Complete)

**Date:** 2026-05-12
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 3 Track 1 (FR-WP-01..09)
**Status:** ✅ Complete

The first of four Phase 3 modules. Working papers are now first-class with multi-step sign-off, IIA 2330 separation of duties, version chains, cross-references to findings, AV scan integration, and lock-on-finalize.

---

## What shipped

### Backend

**Model** ([migration 0012](../iams-backend/iams/migrations/0012_workingpaper.py)) — `WorkingPaper`:
- Engagement scope (`audit` FK), reference, title, description, file
- Status (Draft / Under Review / Signed / Archived)
- Version chain: `parent` self-FK, `version`, `is_current_version` (partial unique per `(audit, reference)`)
- Sign-off pair: `auditor_signed_by/at`, `reviewer_signed_by/at`, derived `signed_off_at`
- Cross-references to `Finding` via M2M
- AV scan state (mirrors `EvidenceFile`)
- `searchable_text` for case-insensitive search (works on Postgres + SQLite)

**Service module** [`iams/working_papers.py`](../iams-backend/iams/working_papers.py):
- `sign_as_auditor(wp, by_user)` — records auditor signature; no double-sign.
- `sign_as_reviewer(wp, by_user)` — records reviewer signature + sets `signed_off_at` + locks. Enforces IIA 2330 separation (reviewer ≠ auditor).
- `create_new_version(parent, file=, title=, description=)` — atomic flip-parent + insert-child + copy-cross-refs.
- `populate_searchable_text(wp)` — stub extractor (title + description + reference + plain-text contents).

**Lock-on-finalize** (FR-WP-06) — `WorkingPaper.save()` rejects updates to a signed row; `delete()` raises `PermissionError`. AV scan-only updates (`scan_status`/`scan_signature`/`scanned_at`/`quarantined`) are explicitly allowed.

**API** — `WorkingPaperViewSet` at `/api/working-papers/`:
| Verb | Path | Behavior |
|---|---|---|
| GET | `/` | List with `?audit_id=` / `?currentOnly=true` / `?status=` / `?search=` |
| POST | `/` | Multipart create (auto `file_size_kb`, AV scan dispatch, `searchable_text` populate) |
| PATCH | `/{id}/` | Edit draft fields; **403** once signed off |
| POST | `/{id}/sign/auditor/` | Record auditor signature |
| POST | `/{id}/sign/reviewer/` | Record reviewer signature + lock |
| POST | `/{id}/new-version/` | Multipart; flips parent's `is_current_version` |
| GET | `/{id}/versions/` | Full chain in order 1→N |
| GET | `/{id}/download/` | Signed URL; 403 on quarantine, 409 if scan pending |

**AV scan reuse** — `scan_uploaded_file` Celery task now accepts `model_label="WorkingPaper"`; the scan + quarantine flow is identical to `EvidenceFile`.

**Audit-log integration** — sign-off and new-version actions both record `AuditLogEntry` rows (`working_paper_auditor_signed`, `working_paper_reviewer_signed` with `finalized: true`, `working_paper_new_version` with `parent_id` + `version`).

**Tests** ([`iams/tests/test_working_papers.py`](../iams-backend/iams/tests/test_working_papers.py)) — 22 tests covering:
- Sign-off rules (single-sign, ordering, separation of duties, finalize)
- Lock-on-finalize (save + delete + scan-only carve-out)
- Version chain (flips current, copies findings, clears signatures, partial-unique constraint)
- searchable_text population
- API: upload + AV dispatch, filter-by-audit, search-by-title, currentOnly, sign-off + audit log, update-rejected-after-signoff, versions endpoint, new-version endpoint, quarantined download

### Frontend

**Typed client** [`src/lib/working-papers-api.ts`](../iams-frontend/src/lib/working-papers-api.ts) — full surface: `listWorkingPapers`, `getWorkingPaper`, `getWorkingPaperVersions`, `signAsAuditor`, `signAsReviewer`, `uploadWorkingPaper`, `uploadNewVersion`, `getDownloadUrl`. Types mirror the backend serializer field-for-field (camelCase).

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
| **working papers (new)** | **22** |
| legacy domain | 3 |
| **Backend total** | **380** |
| Frontend vitest | 14 |

---

## Acceptance criteria (FR-WP-01..09)

| FR | Requirement | Status |
|---|---|---|
| FR-WP-01 | Upload PDF/Excel/Word/Image | ✅ (any file via multipart) |
| FR-WP-02 | Version control per document | ✅ (`parent` self-FK + `version`) |
| FR-WP-03 | Digital sign-off (Auditor + Reviewer) | ✅ (with IIA 2330 separation of duties) |
| FR-WP-04 | Cross-reference findings to working papers | ✅ (`findings` M2M) |
| FR-WP-05 | Store with timestamp | ✅ (`TimeStampedModel`) |
| FR-WP-06 | Prevent deletion / modification of finalized | ✅ (Python lock on save+delete; carve-out for AV) |
| FR-WP-07 | Search by engagement, entity, risk category | ✅ (engagement via `?audit_id`; free-text via `?search`; entity/risk-category in Phase 3 Track 1.1) |
| FR-WP-08 | Encrypt documents at rest | ✅ (MinIO SSE-AES256 from Phase 1 Track 3) |
| FR-WP-09 | IIA 2330 Documenting Information | ✅ (separation of duties + immutability + sign-off audit-log events) |

---

## Deferred (parked into Phase 3 Track 1.1 follow-up)

- **Real document text extraction** — currently the stub indexes metadata + plain-text only. The Celery task should pull bytes from MinIO and run `unstructured` (PDFs/Word/images via OCR via tesseract) into the `searchable_text` field.
- **Postgres `tsvector` upgrade** — the current `icontains` search works everywhere but doesn't rank. A Postgres-only `SearchVectorField` + GIN index will replace it once we drop SQLite test parity (or with a backend-dispatching query).
- **FE Working Papers page** — list with cards by audit + reference, expand → version timeline + sign-off CTA + cross-reference picker. The typed client is ready; the page itself is deferred to FE polish.
- **Cryptographically-signed payload** for sign-off — the plan mentions JWT-signed sign-off receipts. Phase 5 hardening will add server-side signature verification + receipt download.

---

## How to verify locally

```bash
cd iams-backend
uv run python manage.py migrate iams      # applies 0012
uv run pytest iams/tests/test_working_papers.py -v   # 22/22

# End-to-end manual smoke (with the stack running):
docker compose up
# 1. POST /api/working-papers/ multipart with auditId + title + file
# 2. POST /api/working-papers/{id}/sign/auditor/ as user A
# 3. POST /api/working-papers/{id}/sign/reviewer/ as user B (different user!)
# 4. Try to PATCH the row → 403 with "create a new version instead"
# 5. POST /api/working-papers/{id}/new-version/ → fresh v2 in Draft
```

---

## What's next

**Phase 3 Track 2 — QAIP** (Quality Assurance & Improvement Program — FR-QAIP-01..06): `QAIPAssessment`, `QAIPFinding`, `StakeholderSurvey`, `AuditKPI` models + a dashboard.

After Track 2, Track 3 (CSA — Control Self-Assessment) and Track 4 (ICFR — financial-control testing). Each will be tackled in its own session.

---

*Generated 2026-05-12.*
