# Phase 5 Track 4 — CI/CD (Complete)

**Date:** 2026-05-13
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 5 Track 4
**Status:** ✅ Complete

This track replaces the old SSH-shell `deploy.sh` (gone) with a fail-closed pipeline: PR → CI (lint, typecheck, tests, contract export) → main merge → image build → Trivy scan → blue-green deploy to staging → smoke test → manual promote to production. Backups and a quarterly restore drill make the disaster-recovery story end-to-end testable.

---

## What shipped

### CI ([`.github/workflows/ci.yml`](../.github/workflows/ci.yml))

Three parallel jobs with `concurrency: cancel-in-progress` so a fresh push kills the in-flight run on the same branch:

| Job | Steps |
|---|---|
| `backend` | `uv sync` → ruff (soft) → `makemigrations --check --dry-run` (hard) → `pytest --cov` → upload coverage |
| `frontend` | `npm ci` → `tsc --noEmit` (hard) → `npm run lint` (soft) → `npm run build` → upload dist |
| `contract` | depends on both above; exports the OpenAPI schema via `spectacular` and uploads it |

Hard gates fail the build; soft gates are advisory until the ruff / ESLint config lands.

### Release pipeline ([`.github/workflows/release.yml`](../.github/workflows/release.yml))

| Stage | What |
|---|---|
| `images` | Build both Dockerfiles with Buildx + gha cache, tag with `sha-{12-char}` or git tag, push (if registry creds set), **Trivy** scan for `CRITICAL,HIGH` with `ignore-unfixed`, upload SARIF to GitHub Security |
| `deploy-staging` | Auto on `main` push. Runs `deploy/blue_green.sh` → `deploy/smoke_test.sh`. Protected `staging` environment scope. |
| `deploy-production` | Triggered by tag push or manual `workflow_dispatch` with `deploy_to=production`. Protected `production` environment scope (requires reviewer approval). |

### Blue-green deploy ([`deploy/blue_green.sh`](../deploy/blue_green.sh))

The migration is run **inside the new color's container before the traffic flip**. The five steps:

1. Read `/opt/iams/current-color` to find the live color.
2. Pull images → `migrate` inside the new color → start the new color.
3. Poll `/ready/` on the new color until 200 or timeout.
4. `ln -sfn upstream-${new}.conf upstream.conf` + `nginx -s reload`.
5. 30s drain, then stop the old color.

Failure modes:
- **Migration fails** → exit non-zero. Symlink untouched. Old color still serves.
- **Health check times out** → exit 2. Old color still serves. New color left running for forensics.
- **Smoke test fails after swap** → CI marks deploy as failed; operator decides revert or roll-forward.

### Smoke test ([`deploy/smoke_test.sh`](../deploy/smoke_test.sh))

`curl` against `/health/`, `/ready/`, `/metrics`, `/api/schema/`, `/`, and `/api/audits/` (expecting 401 — confirms auth wiring).

### Docker stack ([`docker-compose.yml`](../docker-compose.yml))

| Service | Purpose | Profile |
|---|---|---|
| `postgres` | Primary DB with health check | shared |
| `pgbouncer` | Connection pooling (transaction mode, 200 client / 25 server) | shared |
| `redis` | Cache + Celery broker, AOF on | shared |
| `minio` | S3-compatible storage for evidence + reports | shared |
| `clamav` | AV daemon for evidence uploads | shared |
| `backend-blue` / `backend-green` | Gunicorn workers | `blue` / `green` |
| `frontend-blue` / `frontend-green` | nginx-served SPA bundle | `blue` / `green` |
| `celery-worker` / `celery-beat` | Async tasks + scheduler | shared |
| `nginx` | Reverse proxy with TLS termination | shared |

### Frontend Dockerfile ([`iams-frontend/Dockerfile`](../iams-frontend/Dockerfile))

Two-stage: `node:20-alpine` → `npm run build`, then `nginx:1.27-alpine` serves the Vite dist with:
- Aggressive caching on `/assets/` (`max-age=1y, immutable`)
- Short cache on favicons / robots
- No-cache on `index.html` (SPA fallback)
- gzip on text/JSON/SVG/woff2
- Container-internal `/healthz`
- Non-root `nginx` user, listens on 8080 inside the container

### Backups ([`deploy/backup.sh`](../deploy/backup.sh) + [`deploy/restore.sh`](../deploy/restore.sh))

Pipeline:

```
pg_dump (custom)  + MinIO mirror
        │
        ▼
tar + age (multi-recipient pubkey)
        │
        ▼
restic → NAS (primary)
       └→ offsite (optional)
```

Retention: 7 daily / 4 weekly / 12 monthly. Restore script supports `latest` or a specific snapshot ID; decrypts with the age identity file and `pg_restore`s into a target DB URL. The quarterly drill is what verifies the chain end-to-end.

### Migration checklist ([`MIGRATION-CHECKLIST.md`](../MIGRATION-CHECKLIST.md))

Codifies the N-1 rule (the old app must work with the new schema, the new app must work with the old data shape) plus the specific patterns: NOT NULL columns, renames, concurrent index creation, model deletion, data migrations with reverse_code. The CI's `makemigrations --check --dry-run` is the auto-gate; the checklist is the human gate.

---

## Decisions

- **Fail-closed everywhere.** Broken migration → deploy aborts with old color live. Trivy finds a CRITICAL → release job fails before push. Health check times out → swap doesn't happen. No automatic rollback on smoke-test failure (the swap already happened by then) — operator chooses revert or roll-forward, because either could be the right call.
- **`migrate` runs inside the new color, before traffic flips.** This is the single most important rule. A migration that fails on production-shaped data takes down the deploy, not the system.
- **`makemigrations --check` in CI is a hard gate.** Forgetting a migration is a recurring source of "works on my machine"; the check catches it before merge.
- **Trivy `ignore-unfixed: true`.** Findings without an upstream fix can't be acted on — let them light up in the Security tab as advisories rather than gate every deploy on unresolvable noise.
- **Blue-green via two `compose` profiles + a symlink, not Kubernetes.** The plan is explicit about on-prem docker-compose. The symlink + `nginx -s reload` swap is atomic enough; rolling Kubernetes is Phase 6+ territory.
- **`age` for backup encryption.** Multi-recipient (the operator team can decrypt without sharing keys); modern crypto (no GPG ceremony); restic provides dedup and retention.

---

## What's deferred to operator

- Provisioning Harbor / Gitea Actions runner on-prem.
- Setting `STAGING_HOST`, `PROD_HOST`, `*_DEPLOY_KEY`, `REGISTRY_USERNAME`, `REGISTRY_PASSWORD` secrets in GitHub.
- Creating the `staging` and `production` GitHub environments + setting required reviewers.
- Generating the age recipient keys + provisioning the restic repos.
- Cron entry for `deploy/backup.sh`.
- Scheduling the quarterly restore drill.

---

## Phase 5 — Close-out

Phase 5 is complete. Across four tracks:

| Track | Version | Tests added | Lines (rough) |
|---|---|---:|---:|
| 1: Security | `0.16.0` | +24 | ~1,200 BE + ~150 FE |
| 2: Performance & Scale | `0.17.0` | +9 | ~150 BE + perf tests + locust |
| 3: Observability | `0.18.0` | +13 | ~700 BE + ops assets |
| 4: CI/CD | `0.19.0` | 0 | ~700 ops (CI / compose / deploy / docs) |
| **Phase 5 total** | | **+46** | |

- **Tests: 540 → 586** (all green with `IAMS_DISABLE_PDF_RENDER=1`).
- **Migrations: 0017 → 0019** (security + perf indexes).
- **Two new envelopes** the system now stands on: structured logging + a Prometheus story end-to-end, and an automated deploy pipeline with rollback safety.

Next: **Phase 6 — Integrations & Polish** (Keycloak SSO, ERP/HR integrations, accessibility audit, documentation).
