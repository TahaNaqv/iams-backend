# Changelog

All notable changes to the IAMS Django REST API backend.

## [0.5.0] — Phase 1 Track 3: MinIO storage + ClamAV virus scanning (2026-05-12)

### Added
- **Antivirus scanning of uploads** — every `EvidenceFile` and `ManagedDocument` upload is scanned asynchronously by `iams.tasks.scans.scan_uploaded_file` (Celery + `clamd` over TCP INSTREAM).
- **`clamd>=1.0.2`** dependency in `pyproject.toml`.
- New model fields on both `EvidenceFile` and `ManagedDocument` (migration 0007): `scan_status` (`pending`/`clean`/`infected`/`error`), `scan_signature`, `scanned_at`, `quarantined`. Exposed in serializers as `scanStatus`/`scanSignature`/`scannedAt`/`quarantined`.
- **`clamav` service** in `docker-compose.yml` — runs `clamav/clamav:stable` with healthcheck (note: first boot downloads ~250MB of virus definitions; `start_period: 600s`).
- **CLAMD configuration** in `config/settings/base.py`: `CLAMD_HOST` / `CLAMD_PORT` / `CLAMD_SCAN_TIMEOUT` / `CLAMD_MAX_FILE_MB` / `CLAMD_SKIP` (escape hatch for dev/CI without clamd).
- **13 scan-flow tests** in `iams/tests/test_scans.py` — clean / infected / scan error / `CLAMD_SKIP` / oversize / missing row / unknown model_label / upload-dispatches / 403-quarantined-download / 409-pending-download / clean-download / managed-document upload / managed-document-quarantined-hides-downloadUrl.

### Behavior
- **Fail-closed** — any clamd error or oversize file is marked `quarantined=True`; humans must clear it.
- **Download endpoint** (`GET /api/evidence-files/<id>/download/`) now:
  - 403 if quarantined (with `scanStatus` + `scanSignature` in body)
  - 409 if scan still pending
  - 200 with signed URL otherwise (MinIO returns presigned URL via `django-storages` when `USE_S3_STORAGE=1`; FileSystemStorage returns the absolute media URL in dev)
- **ManagedDocument `downloadUrl`** is `null` when quarantined — the FE cannot accidentally link to a virus-flagged file.
- **Rescan on file replace** — `ManagedDocumentViewSet.perform_update` resets scan state and dispatches a new scan if the `file` field changes.

### Test totals
- **Backend: 304 tests passing** (was 291; added 13 scan tests). Coverage stable.

## [0.4.0] — Phase 1 Track 2: Contract Conformance (2026-05-12)

### Added
- **`iams/tests/test_contract.py`** — **32 contract conformance tests**, one per major endpoint, asserting the JSON response shape matches the frontend's TypeScript model exactly (every camelCase field present, no snake_case leaks, list/dict types correct). This file is the **executable version** of `iams-frontend/docs/api-contract.md`.
- `cell` field on `RiskAssessmentImportIssue` model — added via [migration 0006](iams/migrations/0006_rename_sheet_name_riskassessmentimportissue_sheet_and_more.py) to match the FE contract `{sheet, cell}`.

### Fixed (drift caught by the new contract suite)
- `RiskAssessmentImportIssue` had `sheet_name` / `row_number` model fields with `sheetName` / `rowNumber` serializer keys. The FE contract expects `sheet` / `cell`. Renamed the field, added the new one, simplified the serializer.

### Changed
- `DefaultPagination.page_size` bumped 25→100 (max stays 200) so the existing FE list pages (which do not yet render pagination controls) don't silently truncate. Phase 4 dashboard work will reintroduce 25-per-page once the UI catches up.
- `order_by()` added to: `UserViewSet`, `ChecklistItemViewSet`, `EvidenceFileViewSet`, `AuditableEntityViewSet`, `FollowUpViewSet`, `AssignmentViewSet`, `HoursBudgetViewSet`, `RiskAssessmentViewSet`. Silences DRF's `UnorderedObjectListWarning` and gives paginated lists deterministic ordering.

### Notes
- All 291 backend tests passing. Coverage stable.
- Per the plan, the FE convention `pendingCAPs` (acronym preserved) was kept rather than normalized to `pendingCaps` — the FE i18n keys, mock data, and components all use the acronym form.

## [0.3.0] — Phase 1 Milestone: Auth Hardening + RBAC Matrix (2026-05-12)

### Added — Auth endpoints
- `POST /api/auth/password/reset/` — anonymous password-reset request. Always returns 202 to prevent email enumeration. Sends email via Celery (`iams.send_password_reset_email`) using `default_token_generator`.
- `POST /api/auth/password/reset/confirm/` — completes reset with `{uid, token, new_password}`. Validates token, enforces password complexity (≥12 chars by default), invalidates token on success (single-use).
- `POST /api/auth/password/change/` — authenticated password change requiring current password.
- `PATCH /api/auth/me/` — users can edit own `first_name`, `last_name`, `email` (role/status remain admin-only).
- Email templates at `iams/templates/iams/email/password_reset.{txt,html}` (plain-text + responsive HTML).
- Celery task `iams.send_password_reset_email` with autoretry (3×, exponential backoff up to 10min, jitter).

### Added — Test infrastructure
- `iams/tests/test_auth.py` — 19 tests covering every auth endpoint, including a full round-trip (request → email → confirm → new login).
- `iams/tests/test_rbac_matrix.py` — **232 tests** asserting every endpoint × every role returns the expected 200/403, plus anonymous-rejection on every endpoint. This is the central RBAC guarantee.

### Fixed
- `ChecklistItemViewSet` required `edit_audits` even for GET — drift from the API contract caught by the new RBAC matrix test. Now uses `get_permissions()` to require `view_audits` for read and `edit_audits` for write (mirrors `AuditViewSet`).
- `RiskAssessmentMatrixViewSet`, `RiskAssessmentSummaryViewSet`, `RiskAssessmentImportIssuesViewSet` — added `order_by` to silence `UnorderedObjectListWarning` and stabilize pagination.
- `drf-spectacular` post-processing hook moved to the correct `drf_spectacular.contrib.djangorestframework_camel_case.camelize_serializer_fields` path.

### Changed
- Removed `djangorestframework-camel-case` parser/renderer from REST_FRAMEWORK defaults. The existing 30+ serializers already declare camelCase field names explicitly via `source="snake_case"` — adding the auto-translator caused double translation. Documented in `config/settings/base.py`.
- `config/settings/test.py` now also zeros out `DEFAULT_THROTTLE_RATES` so views with explicit `throttle_classes = [ScopedRateThrottle]` don't fire 429s in tests.
- Throttling on all auth-modifying endpoints is `auth_burst` (10/min) for brute-force resistance.

### Notes
- Frontend pages now reach `/api/auth/password/reset/` and `/api/auth/password/reset/confirm/` directly (no JWT required).
- All 259 backend tests passing. Coverage at 85%.

## [0.2.0] — Phase 0: Foundation Hardening (2026-05-12)

### Added
- **Settings split** — `config/settings/` package with `base.py`, `dev.py`, `prod.py`, `test.py`. Production fails fast on missing secrets; dev permits a local SQLite fallback.
- **`django-environ`** replaces `python-decouple`; supports `DATABASE_URL` parsing and proper list/bool casting.
- **OpenAPI 3.1 schema** via `drf-spectacular` + `drf-spectacular-sidecar`. Routes:
  - `/api/schema/` — raw schema (YAML/JSON)
  - `/api/docs/` — Swagger UI
  - `/api/redoc/` — ReDoc
- **Pagination** — `iams/pagination.py` with `DefaultPagination` (page 25, max 200), `LargeResultsPagination`, `AuditLogCursorPagination`. Wired as DRF default.
- **CamelCase JSON contract** — `djangorestframework-camel-case` renderer/parser pair. Python stays snake_case internally; FE sees camelCase.
- **Custom exception handler** — `iams/exceptions.py` adds `requestId` correlation to every error payload and logs unhandled exceptions to Sentry/Loki.
- **Soft delete mixin** — `iams/mixins.py` with `SoftDeleteMixin`, `SoftDeleteManager`, `SoftDeleteQuerySet`. To be applied via migration to user-facing tables in Phase 2.
- **Celery** — `config/celery.py` app + `celery[redis]`, `django-celery-beat`, `django-celery-results`, `flower`. Test-time tasks run eagerly.
- **Caching** — Redis-backed via `django-redis`. Wired in base settings with graceful degradation (`IGNORE_EXCEPTIONS=True`).
- **JWT hardening** — `simplejwt.token_blacklist` app installed, rotation enabled, `BLACKLIST_AFTER_ROTATION=True`. New endpoint: `/api/auth/token/blacklist/`.
- **Production-shape Dockerfile** — multi-stage build, non-root `iams` user, runs gunicorn + tini, healthcheck included, runtime libs only (no compilers).
- **Container entrypoint** — `docker/entrypoint.sh` dispatches `web` / `worker` / `beat` / `flower` / `migrate` / `shell` / `manage` commands.
- **Local docker-compose stack** — postgres, redis, minio (+ bootstrap that creates buckets), mailhog, backend (gunicorn), celery worker, celery beat, flower.
- **WhiteNoise** static files serving in containerized envs.
- **Object storage** — `django-storages[boto3]` for MinIO/S3. Configured in `prod.py` with SSE-AES256, signed-URL downloads (15-min expiry).
- **Observability scaffolding** — `django-prometheus` (`/metrics/`), `sentry-sdk[django]`, OpenTelemetry instrumentation packages.
- **Email pipeline** — `django-anymail[smtp]`; dev points at mailhog, prod at SMTP relay.
- **Security packages declared for Phase 5** — `django-otp`, `django-two-factor-auth`, `django-csp`, `django-axes`.
- **SSO packages declared for Phase 6** — `mozilla-django-oidc`, `hvac` (Vault client).
- **Report generation packages** — `weasyprint`, `openpyxl`, `jinja2`.
- **Test stack** — `pytest`, `pytest-django`, `pytest-cov`, `pytest-xdist`, `factory-boy`, `freezegun`, `model-bakery`, `responses`. Tests in `iams/tests/` package with `conftest.py` fixtures (RBAC users, authed clients, factories).
- **Lint/format/type-check** — `ruff` + `black` + `mypy` (with `django-stubs` + `drf-stubs`); strict mypy on `iams/views/*` and `iams/serializers`. Pre-commit config (`.pre-commit-config.yaml`) with whitespace, secret-detection, large-file, ruff, black, mypy, pip-audit (manual) hooks.
- **Smoke tests** — `iams/tests/test_smoke.py` covering health, readiness, OpenAPI schema, JWT auth, anonymous rejection.

### Changed
- `Dockerfile` rewritten as multi-stage with gunicorn entrypoint, non-root user, healthcheck.
- `docker-compose.yml` now includes redis, minio, mailhog, celery worker/beat/flower services with proper depends_on + healthchecks.
- `.env.example` rewritten with all new env vars (sections: core, CORS, DB, Redis, JWT, S3/MinIO, email, super-admin, Sentry, OIDC, Vault, Gunicorn tuning, feature flags).
- `config/wsgi.py`, `config/asgi.py` point at `config.settings.prod` by default; `manage.py` defaults to `config.settings.dev`.
- `config/urls.py` adds schema/docs/redoc/metrics routes and JWT blacklist endpoint.
- `iams/middleware.py` exports `get_current_request_id()` for use in the new exception handler.

### Removed
- Monolithic `config/settings.py` — replaced by the settings package.
- `python-decouple` — replaced by `django-environ`.

### Notes
- This release establishes the production posture. **Existing migrations are unchanged**; no data migration required.
- Next steps (Phase 1): wire FE to real backend, add password reset endpoints, switch evidence storage to MinIO, lock RBAC matrix via test suite.

## [0.1.0] — Initial release

- Django 6.0.2 + DRF + SimpleJWT + 40 models in single `iams` app + 28+ REST resources, 5 migrations, RBAC, request-ID tracing, health/ready endpoints, RBAC seed command.
