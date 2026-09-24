# IAMS Admin Guide

For operators, IT admins, and SREs. Covers deployment, configuration, integrations, monitoring, and break-glass procedures.

## Table of contents

1. [Architecture overview](#architecture-overview)
2. [Environment variables](#environment-variables)
3. [Initial deployment](#initial-deployment)
4. [Day-2 operations](#day-2-operations)
5. [Keycloak SSO setup](#keycloak-sso-setup)
6. [ERP / HR integrations](#erp--hr-integrations)
7. [Backup & restore](#backup--restore)
8. [Monitoring & alerting](#monitoring--alerting)
9. [Troubleshooting](#troubleshooting)

---

## Architecture overview

```
                        ┌─────────────────────┐
   browser ──HTTPS──▶   │  nginx (TLS, blue-  │
                        │  green upstream)    │
                        └────┬──────────┬─────┘
                  ┌──────────┘          └──────────┐
            ┌─────▼────────┐               ┌───────▼──────┐
            │ frontend     │               │ backend      │
            │ nginx:alpine │               │ gunicorn+    │
            │ SPA bundle   │               │ Django REST  │
            └──────────────┘               └─┬────────────┘
                                             │
        ┌────────────────┬────────────────┬──┴──┬───────────────┐
        ▼                ▼                ▼     ▼               ▼
    Postgres 16      Redis 7          MinIO    Celery        ClamAV
   (pgbouncer)     (cache+broker)    (S3 obj) worker+beat   (AV scan)
                                                  │
                                                  └─ outbound HTTPS ─▶ ERP/HRIS
```

### External dependencies

- **Keycloak** — corporate SSO (federated with AD via LDAP). See [Keycloak SSO setup](#keycloak-sso-setup).
- **Prometheus** + **Grafana** + **Loki** + **Tempo** — observability stack (assets in [`deploy/grafana/`](../deploy/grafana/), [`deploy/prometheus/`](../deploy/prometheus/)).
- **Sentry** (self-hosted) — error tracking. Just set `SENTRY_DSN` in prod.
- **NAS** + **offsite repo** — restic backup destinations.

---

## Environment variables

All settings are env-driven via [`django-environ`](https://django-environ.readthedocs.io/). Required vars are loud-failures (raise on missing); optional vars have sensible defaults.

### Core

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `DJANGO_SETTINGS_MODULE` | yes | — | `config.settings.prod` in production |
| `SECRET_KEY` | yes (prod) | dev placeholder | Django session signing |
| `DEBUG` | no | `false` | Never `true` in prod |
| `ALLOWED_HOSTS` | yes (prod) | `localhost,127.0.0.1` | Comma-separated FQDNs |
| `DATABASE_URL` | yes (prod) | SQLite | `postgres://iams:pw@pgbouncer:6432/iams` |
| `REDIS_URL` | no | `redis://localhost:6379/0` | Cache + Celery broker |
| `CELERY_BROKER_URL` | no | mirror of `REDIS_URL` | |
| `TIME_ZONE` | no | `UTC` | Use the org's business-hours zone |

### JWT

| Variable | Default | Purpose |
|---|---|---|
| `JWT_ACCESS_MINUTES` | `15` | Short-lived access token |
| `JWT_REFRESH_DAYS` | `7` | Refresh token lifetime |

### Security (Phase 5 Track 1)

| Variable | Default |
|---|---|
| `IAMS_LOGIN_FAIL_THRESHOLD` | `5` |
| `IAMS_LOGIN_LOCKOUT_MINUTES` | `15` |
| `IAMS_LOGIN_FAIL_WINDOW_MIN` | `15` |
| `IAMS_PASSWORD_HISTORY_N` | `5` |
| `IAMS_MFA_GRACE_DAYS` | `30` |
| `IAMS_MFA_TOTP_ISSUER` | `IAMS` |
| `IAMS_SESSION_INACTIVITY_MINUTES` | `60` |
| `IAMS_CSP` | safe default | Override to tighten the Content-Security-Policy |

### Storage (MinIO / S3)

| Variable | Required (prod) |
|---|---|
| `S3_BUCKET_NAME` | yes |
| `S3_ENDPOINT_URL` | yes |
| `S3_ACCESS_KEY` | yes |
| `S3_SECRET_KEY` | yes |
| `S3_REGION` | no (defaults to `us-east-1`) |
| `S3_USE_SSL` | no (defaults true) |
| `S3_SIGNED_URL_EXPIRY` | no (defaults 900s) |

### Email (Postfix or relay)

| Variable | Default | Notes |
|---|---|---|
| `EMAIL_BACKEND` | console (dev) / SMTP (prod) | |
| `EMAIL_HOST` / `EMAIL_PORT` / `EMAIL_HOST_USER` / `EMAIL_HOST_PASSWORD` / `EMAIL_USE_TLS` | — | Match the relay |
| `DEFAULT_FROM_EMAIL` | `iams-noreply@example.local` | |

### Antivirus

| Variable | Default |
|---|---|
| `CLAMD_HOST` | `clamav` (compose service) |
| `CLAMD_PORT` | `3310` |
| `CLAMD_SCAN_TIMEOUT` | `60` |
| `CLAMD_MAX_FILE_MB` | `100` |
| `CLAMD_SKIP` | `false` |

### Observability (Phase 5 Track 3)

| Variable | Default | Notes |
|---|---|---|
| `LOG_FORMAT` | `json` | `text` for local dev |
| `IAMS_LOG_ENV` | empty | Surfaces as `env` field in log lines |
| `SENTRY_DSN` | empty | Enables Sentry when set |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | |
| `OTEL_ENABLED` | `false` | Set `true` to enable tracing |
| `OTEL_SERVICE_NAME` | `iams-backend` | |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | default to collector default | OTLP/HTTP, e.g. `http://otel-collector:4318` |
| `OTEL_TRACES_SAMPLER_ARG` | `0.1` | 10% root span sample |

### SSO (Phase 6 Track 1)

| Variable | Default |
|---|---|
| `IAMS_SSO_ENABLED` | `false` |
| `IAMS_SSO_PROVIDER_NAME` | `Corporate SSO` |
| `IAMS_SSO_DEFAULT_ROLE` | `Viewer` |
| `IAMS_SSO_TRUSTS_IDP_MFA` | `true` |
| `OIDC_RP_CLIENT_ID` | — |
| `OIDC_RP_CLIENT_SECRET` | — |
| `OIDC_OP_AUTHORIZATION_ENDPOINT` | — |
| `OIDC_OP_TOKEN_ENDPOINT` | — |
| `OIDC_OP_USER_ENDPOINT` | — |
| `OIDC_OP_JWKS_ENDPOINT` | — |
| `OIDC_OP_LOGOUT_ENDPOINT` | — |
| `OIDC_RP_SIGN_ALGO` | `RS256` |
| `OIDC_RP_SCOPES` | `openid email profile groups` |

---

## Initial deployment

### Prerequisites

- Linux host (Ubuntu 22.04 LTS or RHEL 9 recommended).
- Docker 24+ + Docker Compose v2.
- Reverse proxy (we use the bundled nginx).
- TLS certs (Let's Encrypt via the on-prem ACME endpoint, or a corporate PKI cert).
- DNS A records for `iams.internal` + `staging.iams.internal`.

### Steps

1. **Clone the repo onto the host.**

   ```bash
   git clone git@gitea.internal:iams/iams.git /opt/iams
   cd /opt/iams
   ```

2. **Create `.env`** with the production values (use [`iams-backend/.env.example`](../iams-backend/.env.example) as a template if present; otherwise see the env-vars table above).

3. **First-run seeding.** RBAC permission rows + the Super Admin user need to exist before the FE is usable.

   ```bash
   docker compose run --rm backend-blue python manage.py migrate
   docker compose run --rm backend-blue python manage.py seed_rbac
   ```

4. **Bring up the blue stack.**

   ```bash
   docker compose --profile blue up -d
   echo blue > /opt/iams/current-color
   ```

5. **Verify health.**

   ```bash
   ./deploy/smoke_test.sh
   ```

6. **Wire monitoring** — import `deploy/grafana/*.json` into Grafana, point Prometheus at `/metrics`, drop `deploy/prometheus/iams-alerts.yml` into the rules dir.

---

## Day-2 operations

### Deploys

GitHub Actions handles staging on every `main` push and production on tag push / manual `workflow_dispatch`. See [`.github/workflows/release.yml`](../.github/workflows/release.yml). The blue-green script ([`deploy/blue_green.sh`](../deploy/blue_green.sh)) runs migrations inside the new color *before* flipping traffic — a broken migration aborts the deploy with the old color still live.

To roll back: `ln -sfn upstream-blue.conf upstream.conf && nginx -s reload` (or use the previous tag's image).

### Adding a permission / role

Permissions are seeded by `python manage.py seed_rbac`. Roles + assignments are admin-side:

```bash
docker compose exec backend-blue python manage.py shell
```

```python
from iams.models import Permission, Role
role = Role.objects.create(name="Compliance Officer", is_super_admin=False)
role.permissions.set(Permission.objects.filter(key__in=["view_audits", "view_reports"]))
```

### Account lockout — admin unlock

```bash
# Find the user
docker compose exec backend-blue python manage.py shell -c \
  "from django.contrib.auth import get_user_model; \
   print(get_user_model().objects.get(email='user@org.example').pk)"

# Via REST
curl -X POST -H "Authorization: Bearer $TOKEN" \
  https://iams.internal/api/auth/lockouts/<user_id>/unlock/
```

---

## Keycloak SSO setup

1. **Create a realm** in Keycloak called `iams`.
2. **Federate AD** via the LDAP provider — AD users appear transparently.
3. **Create an OIDC client** named `iams-backend`:
   - Access type: `confidential`.
   - Valid redirect URIs: `https://iams.internal/api/auth/sso/callback/`, `https://staging.iams.internal/api/auth/sso/callback/`.
   - Web origins: `https://iams.internal`, `https://staging.iams.internal`.
   - Add a `groups` mapper that surfaces user groups in the access token.
4. **Set environment variables** on the IAMS deployment (`OIDC_*` block) — see the env table above.
5. **Set `IAMS_SSO_ENABLED=true`** and restart the backend.
6. **Wire group → role mappings** via `POST /api/sso/group-role-maps/` (admin REST endpoint, requires `manage_settings`).

   Example payload:

   ```json
   { "groupName": "/IAMS/Auditors", "roleId": "<auditor-role-uuid>", "precedence": 10 }
   ```

7. **Test** by navigating to `https://iams.internal/login` — the "Sign in with corporate account" button should now appear.

See [phase-6-track-1-report.md](phase-6-track-1-report.md) for the design rationale.

---

## ERP / HR integrations

1. **Register the source** via `POST /api/integrations/sources/`:

   ```json
   {
     "name": "sap-prod",
     "kind": "sap",
     "status": "active",
     "inboundEnabled": true,
     "inbound_secret": "<generate-a-strong-shared-secret>",
     "outboundEnabled": false
   }
   ```

2. **Configure the external system** to POST to `/api/integrations/webhooks/<source-id>/auditable-entities/` (or `/findings/`) with an `X-IAMS-Signature: sha256=<hex>` header computed as `hmac.sha256(secret, body).hexdigest()`.

3. **Verify deliveries** at `GET /api/integrations/events/?source_id=<id>&direction=inbound` — every payload (accepted or rejected) lands in this ledger with the error message if rejection.

For outbound (push IAMS users to AD/HRIS):

```json
{
  "name": "hris-prod",
  "kind": "hris",
  "outboundEnabled": true,
  "outboundPushesUsers": true,
  "outboundUrl": "https://hris.internal/api/users/",
  "outbound_token": "<bearer-token>"
}
```

Every `User.save()` triggers a fan-out to all active sources with `outboundPushesUsers=true`. See [phase-6-track-2-report.md](phase-6-track-2-report.md) for the design.

---

## Backup & restore

### Nightly backup

Cron entry:

```
0 2 * * * /opt/iams/deploy/backup.sh >> /var/log/iams-backup.log 2>&1
```

Required env on the backup host:

```env
PG_HOST=postgres
PG_DB=iams
PG_USER=iams
PG_PASSWORD=...
MINIO_ENDPOINT=http://minio:9000
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
MINIO_BUCKET=iams-evidence
AGE_RECIPIENTS_FILE=/etc/iams/age-recipients.txt
RESTIC_REPOSITORY=/mnt/nas/iams
RESTIC_PASSWORD=...
RESTIC_OFFSITE_REPOSITORY=sftp:offsite-backup:/iams   # optional
```

Retention: 7 daily / 4 weekly / 12 monthly snapshots (pruned by `restic forget --prune` in the script).

### Quarterly restore drill

```bash
AGE_IDENTITY_FILE=/etc/iams/age-key.txt \
RESTIC_REPOSITORY=/mnt/nas/iams \
RESTIC_PASSWORD=... \
./deploy/restore.sh latest postgres://iams:dr@drill-replica:5432/iams_drill
```

Then spot-check row counts against production. Don't trust a backup until you've restored it.

---

## Monitoring & alerting

- **Grafana dashboards**: import `deploy/grafana/iams-system.json` and `deploy/grafana/iams-business.json`.
- **Prometheus rules**: drop `deploy/prometheus/iams-alerts.yml` into `/etc/prometheus/rules.d/` and reload.
- **Alert routes**:
  - `severity=page` → PagerDuty
  - `severity=warn` → Slack `#iams-platform`
- **Uptime Kuma** monitors `/health/` and `/ready/`; configure SMS + email + Slack notifications.

Key SLOs to track:
- p95 latency < 500ms on top endpoints
- Error rate < 1%
- Celery queue depth < 1000
- Overdue CAP count (operational signal, not failure)

---

## Troubleshooting

### "MFA required" loop on login

The user's role has `mfa_required=true` but they don't have a confirmed TOTP device. Either:

1. Have the user enroll: log in once via the password flow (it'll prompt for MFA setup), or
2. Disable MFA enforcement for their role temporarily: `Role.objects.filter(name='X').update(mfa_required=False)`.

### Webhook returns `signature_invalid`

- The shared secret in `IntegrationSource.inbound_secret` doesn't match what the sender used.
- The body was modified by an intermediate proxy (e.g., transcoded JSON whitespace). HMAC is byte-exact.
- Re-issue the secret if compromised: `PATCH /api/integrations/sources/<id>/ { "inbound_secret": "new-strong-secret" }`.

### Slow `/api/dashboard/role/<role>/`

- Confirm Redis is reachable: `docker compose exec backend-blue redis-cli -h redis ping`.
- The first call after the 5-minute cache flush is cold; subsequent calls are < 100ms.
- If consistently slow, run `EXPLAIN ANALYZE` on the heat-map query in psql and verify the Phase 5 Track 2 indexes are present (`\d+ iams_finding` should show the composite `(department, status)` index).

### Deploy aborts at "migrate" step

- Read the worker log: `docker compose logs backend-green`.
- The deploy script left the new color running — fix forward by editing the migration, re-running, or hand-applying the rollback.

For anything not covered here, the per-phase reports in [`docs/`](.) have the design rationale for that component.
