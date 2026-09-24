# IAMS API Reference

The canonical machine-readable contract is the **OpenAPI 3.1 schema** at:

- `GET /api/schema/` — raw YAML
- `GET /api/docs/` — Swagger UI (interactive)
- `GET /api/redoc/` — ReDoc UI

This document is the narrative companion — explains the *why* and the cross-cutting concerns the schema can't tell you.

## Contents

1. [Conventions](#conventions)
2. [Authentication](#authentication)
3. [Pagination](#pagination)
4. [Error envelope](#error-envelope)
5. [Audit & request correlation](#audit--request-correlation)
6. [Domain endpoint groups](#domain-endpoint-groups)
7. [Rate limiting](#rate-limiting)
8. [Generating typed clients](#generating-typed-clients)

---

## Conventions

- **Base URL**: `https://iams.internal/api`
- **Auth**: `Authorization: Bearer <jwt>` on every authenticated request
- **JSON only**: `Content-Type: application/json` for writes
- **Case**: request + response bodies are **camelCase**. The schema's `source="snake_case"` on every serializer field is what bridges to the Django snake_case columns. The OpenAPI camelize hook keeps the schema consistent for client codegen.
- **Dates**: ISO-8601 UTC (`2026-05-13T12:34:56Z`). Date-only fields are `YYYY-MM-DD`.
- **IDs**: UUIDs (string) for domain entities; integer for Django User PK (legacy — Phase 7 candidate to migrate to UUID).

---

## Authentication

### Token issuance — password

```
POST /api/auth/token/
Content-Type: application/json

{ "username": "alice@org.example", "password": "...", "otp_token": "123456" }
```

`otp_token` is required iff the user has a confirmed TOTP device or the user's role has `mfa_required=true`. Possible non-2xx codes:

| HTTP | `code` | Meaning |
|---|---|---|
| 400 | — | Missing username/password |
| 401 | — | Invalid credentials |
| 401 | `mfa_required` | Present an OTP and retry; `mfaEnrolled=false` → redirect to enrollment |
| 401 | `mfa_invalid` | OTP didn't validate |
| 423 | `account_locked` | Wait or contact admin; response carries `lockedUntil` |

Successful response: `{ "access": "...", "refresh": "..." }`. Access token lifetime is 15 min by default; refresh tokens last 7 days and rotate on use (blacklisting the previous one).

### Token issuance — SSO

Server-side flow only — never call from a fetch:

1. `GET /api/auth/sso/config/` to discover whether SSO is enabled.
2. Browser-redirect to `GET /api/auth/sso/login/?return_to=/dashboard`.
3. IdP authenticates the user, redirects to `/api/auth/sso/callback/`.
4. Callback redirects to the FE at `<frontend>/login/sso/callback#access=…&refresh=…&return_to=…`.

See [phase-6-track-1-report.md](phase-6-track-1-report.md) for the design.

### Token refresh + logout

```
POST /api/auth/token/refresh/   {"refresh": "..."}        → {"access": "..."}
POST /api/auth/token/blacklist/ {"refresh": "..."}        → 204
```

---

## Pagination

All list endpoints use page-number pagination with envelope:

```json
{
  "count": 1234,
  "next": "https://.../api/...?page=2",
  "previous": null,
  "page": 1,
  "pageSize": 25,
  "totalPages": 50,
  "results": [ /* ... */ ]
}
```

Defaults: 25 per page, max 200 via `?page_size=`.

A few endpoints don't paginate (small fixed lists like `NotificationPreference`); they return a plain array.

---

## Error envelope

DRF errors render as:

```json
{
  "detail": "Human-readable message.",
  "code": "stable_machine_code",   /* present on most errors */
  "requestId": "abc-123",          /* matches X-Request-ID header */
  "field_errors": {                /* present on 400 validation errors */
    "fieldName": ["This field is required."]
  }
}
```

The `code` taxonomy is curated across the API. Common codes:

| Code | Meaning |
|---|---|
| `account_locked` | Login refused due to active lockout |
| `mfa_required` | Login needs an OTP |
| `mfa_invalid` | OTP didn't validate |
| `signature_invalid` | Inbound webhook HMAC mismatch |
| `payload_invalid` | Webhook payload missing required fields |
| `sso_disabled` | SSO endpoints called when `IAMS_SSO_ENABLED=false` |
| `sso_state_mismatch` | OIDC callback state didn't match session |
| `password_incorrect` | Re-auth for sensitive action failed |
| `totp_already_confirmed` | Trying to enroll TOTP twice |
| `totp_invalid` | TOTP confirmation token wrong |

---

## Audit & request correlation

Every response carries `X-Request-ID`. The same ID lands on every log line emitted while processing the request — search Loki for `request_id=<id>` to see the full trace.

Every state-changing request is recorded in `AuditLogEntry` automatically by the `AuditedViewSetMixin`. Diff format: `{field: {old, new}}` on update, `{snapshot: {...}}` on create/delete.

---

## Domain endpoint groups

The schema groups endpoints into the following tags. Each group's contract is in the OpenAPI doc; the brief below is the *narrative*.

### auth

User identity + credentials + MFA + SSO + lockouts. See above + [admin-guide.md#keycloak-sso-setup](admin-guide.md#keycloak-sso-setup).

### users / roles / permissions

CRUD over the RBAC model. `manage_users` / `manage_roles` / `manage_permissions` perms gate writes.

### audits

`Audit`, `AuditAssignment`, `ChecklistItem`, `TimelineEvent`, `WorkProgram` / `WorkProcedure` / `WorkProcedureStep`.

### findings / corrective-actions

`Finding` (with audit FK + severity / status / due dates) and `CorrectiveAction` (linked to a finding).

### working-papers

Versioned papers with sign-off (separation of duties enforced — auditor and reviewer must differ).

### risk

`RiskFactor`, `RiskScoringModel`, `RiskFactorWeight`, `EntityRiskScore`. Plus three top-level endpoints:

- `POST /api/risk/scores/record/` — submit a new score (direct CRUD on `/scores/` returns 405)
- `GET /api/risk/heat-map/?scoring_model_id=...`
- `POST /api/risk/generate-plan/` — top-N entities → draft `ApprovalRequest`

### qaip / csa / icfr

Quality, control self-assessment, ICFR test / exception / deficiency tracking.

### approvals

`ApprovalRequest` + `ApprovalStep` + `ApprovalChainTemplate`. Approve / reject actions via `/api/approval-requests/<id>/approve/` and `/reject/`.

### reports

Async report job system. Flow:

1. `POST /api/reports/generate/ {kind, parameters}` → 201 with `ReportJob`
2. Poll `GET /api/reports/jobs/<id>/` until `status=completed`
3. `GET /api/reports/jobs/<id>/download/` → `{url, fileSizeKb}` signed URL

12 supported kinds — 9 PDF + 3 Excel. Excel exports additionally require `export_reports` permission.

### dashboard

The aggregator endpoints from Phase 4 Track 3. Cached at 45s TTL; refresh task runs every 5 min.

- `/kpis/` `/trends/` `/risk-heatmap/` `/ratings/` `/activity/` `/upcoming-audits/`
- `/role/<executive|manager|auditor|auditee>/` — pre-composed bundle (per-user cached for auditor/auditee)

### integrations

ERP / HR sources, event ledger, signed inbound webhooks. See [phase-6-track-2-report.md](phase-6-track-2-report.md).

### notifications

Per-user inbox + preferences. Bell polls `/api/notifications/unread-count/` every 60s.

### audit-log

Read-only ledger of every state-changing operation, scoped to `view_reports`. Cursor-paginated.

### system

`/health/`, `/ready/`, `/metrics` (Prometheus exposition format).

---

## Rate limiting

DRF throttles:

| Scope | Rate | Applies to |
|---|---|---|
| `anon` | 60/min | Unauthenticated requests |
| `user` | 300/min | Authenticated requests |
| `auth_burst` | 10/min | Login + password reset + MFA endpoints |

In tests, rates are zeroed. Adjust via `DEFAULT_THROTTLE_RATES` in settings if your scale changes.

---

## Generating typed clients

The FE's typed clients (`iams-frontend/src/lib/*-api.ts`) are hand-rolled to keep the camelCase mapping explicit. For a third-party consumer:

```bash
# Export the schema
curl https://iams.internal/api/schema/ > openapi.yml

# Generate TypeScript types
npx openapi-typescript openapi.yml -o iams-types.ts

# Generate a full SDK (heavier)
npx openapi-generator-cli generate -g typescript-fetch \
  -i openapi.yml -o iams-sdk
```

The schema is regenerated and uploaded as an artifact on every `main` CI run — see `.github/workflows/ci.yml` → `contract` job.
