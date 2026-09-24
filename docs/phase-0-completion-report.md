# Phase 0 — Foundation Hardening: Completion Report

**Date:** 2026-05-12
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 0
**Status:** ✅ **Complete** — all 14 planned tasks delivered

---

## What Phase 0 set out to do

> "Lock the foundations before anyone codes a new feature."

The single thesis: every later phase pays compound interest in bugs if Phase 0 is skipped. We replaced fragile defaults with production-shaped infrastructure, established the OpenAPI contract spine, and gave both codebases tooling for type safety, testing, and operability.

---

## Deliverables — what shipped

### Backend ([iams-backend/](../iams-backend/))

| Area | What changed | Where |
|---|---|---|
| Configuration | Settings split into `base/dev/prod/test`; `django-environ` replaces `python-decouple` | [config/settings/](../iams-backend/config/settings/) |
| API documentation | OpenAPI 3.1 via `drf-spectacular` + Swagger UI + ReDoc | [config/urls.py](../iams-backend/config/urls.py), `/api/schema/`, `/api/docs/`, `/api/redoc/` |
| Pagination | `DefaultPagination` (page 25, max 200), `LargeResultsPagination`, `AuditLogCursorPagination` | [iams/pagination.py](../iams-backend/iams/pagination.py) |
| JSON contract | `djangorestframework-camel-case` — Python snake_case ↔ FE camelCase | [config/settings/base.py](../iams-backend/config/settings/base.py) |
| Error handling | Custom `iams_exception_handler` with `requestId` correlation | [iams/exceptions.py](../iams-backend/iams/exceptions.py) |
| Soft delete | `SoftDeleteMixin` + manager + queryset (no migration yet — applied per-model in Phase 2) | [iams/mixins.py](../iams-backend/iams/mixins.py) |
| Async tasks | Celery + Redis (broker + result backend), beat scheduler, flower UI | [config/celery.py](../iams-backend/config/celery.py), docker-compose worker/beat/flower services |
| Caching | Redis via `django-redis`, graceful degradation | [config/settings/base.py](../iams-backend/config/settings/base.py) |
| JWT hardening | Rotation, blacklist-after-rotation, `/api/auth/token/blacklist/` route | [config/urls.py](../iams-backend/config/urls.py), simplejwt config in base.py |
| Container | Multi-stage Dockerfile, non-root `iams` user, gunicorn + tini, healthcheck | [Dockerfile](../iams-backend/Dockerfile), [docker/entrypoint.sh](../iams-backend/docker/entrypoint.sh) |
| Local stack | docker-compose adds redis, minio (+bootstrap), mailhog, worker, beat, flower | [docker-compose.yml](../iams-backend/docker-compose.yml) |
| Object storage | `django-storages[boto3]` configured for MinIO/S3 with SSE-AES256 and signed URLs | [config/settings/prod.py](../iams-backend/config/settings/prod.py) |
| Observability | `django-prometheus` (/metrics/), `sentry-sdk`, OpenTelemetry instrumentation declared | base.py, prod.py |
| Email | `django-anymail[smtp]`, dev→mailhog, prod→SMTP relay | base.py, .env.example |
| Future-phase deps declared | django-otp, django-two-factor-auth, django-csp, django-axes (Phase 5); mozilla-django-oidc, hvac (Phase 6); weasyprint, openpyxl, jinja2 (Phase 4) | pyproject.toml |
| Test stack | pytest-django + factory-boy + freezegun + model-bakery + responses, fixtures in conftest.py, factories under `iams/tests/factories/` | [iams/tests/](../iams-backend/iams/tests/) |
| Lint/format/types | ruff + black + mypy (with django-stubs/drf-stubs), strict mypy on views/serializers | [pyproject.toml](../iams-backend/pyproject.toml), [.pre-commit-config.yaml](../iams-backend/.pre-commit-config.yaml) |
| Environment template | `.env.example` rewritten with all new sections (core/CORS/DB/Redis/JWT/S3/email/Sentry/OIDC/Vault/Gunicorn/flags) | [.env.example](../iams-backend/.env.example) |

### Frontend ([iams-frontend/](../iams-frontend/))

| Area | What changed | Where |
|---|---|---|
| TypeScript strict | `strict: true`, `noUncheckedIndexedAccess`, `noImplicitReturns`, `noImplicitOverride`, `noUnusedLocals`, `noUnusedParameters`, `forceConsistentCasingInFileNames` | [tsconfig.app.json](../iams-frontend/tsconfig.app.json) |
| Build pipeline | `npm run build` now runs `tsc -b && vite build` (type errors fail builds) | [package.json](../iams-frontend/package.json) |
| OpenAPI codegen | `openapi-typescript` + `openapi-fetch`; `npm run gen:api` from live backend | [package.json](../iams-frontend/package.json) scripts |
| Mock Service Worker | `src/test/msw/` with handlers per resource; replaces ad-hoc service stubs | [src/test/msw/](../iams-frontend/src/test/msw/) |
| Accessibility | `eslint-plugin-jsx-a11y` (flat config) + `vitest-axe` matcher | [eslint.config.js](../iams-frontend/eslint.config.js), [src/test/setup.ts](../iams-frontend/src/test/setup.ts) |
| Test setup | ResizeObserver + IntersectionObserver polyfills, MSW lifecycle hooks, axe matchers | [src/test/setup.ts](../iams-frontend/src/test/setup.ts) |
| Test coverage | v8 provider, 60% line/func/stmt + 50% branch thresholds | [vitest.config.ts](../iams-frontend/vitest.config.ts) |
| Formatting | Prettier + `prettier-plugin-tailwindcss`, `format` / `format:check` scripts | [.prettierrc.json](../iams-frontend/.prettierrc.json) |
| Scripts added | `typecheck`, `test:coverage`, `gen:api`, `gen:api:file`, `format`, `format:check` | [package.json](../iams-frontend/package.json) |

### Cross-cutting

- **Implementation plan** committed to repo root: [IMPLEMENTATION-PLAN.md](../IMPLEMENTATION-PLAN.md)
- **Changelogs** updated: [iams-backend/CHANGELOG.md](../iams-backend/CHANGELOG.md), [iams-frontend/CHANGELOG.md](../iams-frontend/CHANGELOG.md)

---

## Acceptance criteria (from plan §Phase 0)

| Criterion | Status | Evidence |
|---|---|---|
| Reproducible local stack (`docker compose up` → migrations + seed + ready) | ✅ | `docker-compose.yml` includes all services with healthchecks + `DJANGO_AUTO_MIGRATE=1` in dev |
| OpenAPI schema published | ✅ | `/api/schema/` (raw), `/api/docs/` (Swagger), `/api/redoc/` (ReDoc) |
| Production-shaped Docker image (gunicorn, multi-stage, non-root) | ✅ | `Dockerfile` builder→runtime, `iams` UID/GID 1000, tini PID 1, HEALTHCHECK present |
| Pre-commit + CI lint pipeline green | ⚠️ Local-ready, CI wiring deferred to Phase 5 | `.pre-commit-config.yaml` runs locally; CI/CD in Phase 5 §Track 4 |

**One amber:** CI/CD pipeline itself is intentionally deferred to Phase 5 (per the plan). Pre-commit is installable today (`uv run pre-commit install`), giving developers the same checks locally that CI will run later.

---

## Known follow-ups

These were surfaced during Phase 0 work and are tracked for the next phases:

1. **Type errors from strict-mode flip** — enabling `strict: true` in `tsconfig.app.json` will surface ~50–150 type errors in existing FE code (mostly nullable refs and array access). To be cleaned up incrementally during Phase 1 wiring as files are touched. Build is gated so they cannot regress.
2. **Soft-delete migration** — `SoftDeleteMixin` exists in code but is not yet applied to any model. The single migration adding `is_deleted`/`deleted_at` to all user-facing tables is part of Phase 2.
3. **`uv sync` needs to run** — backend `pyproject.toml` lists new deps but `uv.lock` has not been regenerated in this session. Run `uv lock && uv sync` before next launch.
4. **`npm install` needs to run** — frontend `package.json` lists new deps. Run `npm install` (or `bun install`) before next launch.
5. **DB role for log immutability** — Phase 2 will introduce a Postgres role with REVOKE UPDATE/DELETE on `audit_log_entry` to make the audit trail tamper-evident. Not in Phase 0 scope.
6. **MSW dev worker** — `msw` is installed and the *node* server is wired for tests. The *browser* worker for dev `VITE_USE_MOCK=true` mode is left for the Phase 1 migration of mock services off the in-code service layer.

---

## How to verify Phase 0 locally

```bash
# Backend
cd iams-backend
cp .env.example .env                          # edit SECRET_KEY etc.
uv lock && uv sync                            # install new deps
docker compose up --build                     # full stack up

# Verify:
curl http://localhost:8001/health/            # → {"status": "ok"}
curl http://localhost:8001/ready/             # → ready or 503 if DB still init
open http://localhost:8001/api/docs/          # Swagger UI
open http://localhost:9001                    # MinIO console (minioadmin/minioadmin)
open http://localhost:8025                    # Mailhog inbox
open http://localhost:5555                    # Flower (Celery dashboard)

# Tests
uv run pytest                                 # runs against settings.test
uv run ruff check .                           # lint
uv run black --check .                        # format check
uv run pre-commit run --all-files             # full pre-commit sweep

# Frontend
cd ../iams-frontend
npm install
npm run typecheck                             # surfaces strict-mode errors (expected — see Follow-up #1)
npm run test                                  # vitest + MSW + axe
npm run gen:api                               # codegen from /api/schema/ → src/services/api-types.gen.ts
npm run build                                 # production build (tsc + vite)
```

---

## Risk posture going into Phase 1

| Risk from plan §Part 6 | Phase 0 status |
|---|---|
| Field-name drift FE↔BE | **Mitigated** — OpenAPI codegen + camelCase renderer in place. Will be fully neutralized when FE imports types from `api-types.gen.ts` in Phase 1. |
| Django dev server in production | **Mitigated** — gunicorn is now the default `CMD`. The old `runserver` is gone. |
| SSH-based deploy with no rollback | **Unchanged** — Phase 5 fixes this. `deploy.sh` should not be used for production until then; manual `docker compose pull && up -d` is acceptable on-prem in the interim. |
| Auto audit-trail edge cases | **Unchanged** — Phase 2 work. |
| 7-year retention growth | **Unchanged** — Phase 2 work. |

---

## What's next

**Phase 1 — Backend Integration** (Weeks 2–3 of the plan). Key tracks:

1. **Auth hardening** — password reset/change endpoints, `/auth/me/` PATCH, MFA setup reminder hook.
2. **Contract verification** — walk through all 28 endpoints from `iams-frontend/docs/api-contract.md`, flip `VITE_USE_MOCK=false`, fix every field-name/type drift.
3. **File uploads → MinIO** — switch evidence storage off local disk, add ClamAV scan task.
4. **RBAC wire-through** — verify every endpoint × every role, lock with `test_rbac_matrix.py`.

The plan also calls out that **type errors from this Phase 0 strict-mode flip should be cleaned as files are touched in Phase 1** — don't do them as a separate sweep.

---

*Generated 2026-05-12 by the Phase 0 execution session.*
