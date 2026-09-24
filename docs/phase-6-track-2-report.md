# Phase 6 Track 2 — ERP / HR Integrations (Complete)

**Date:** 2026-05-13
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 6 Track 2 (FR-INT-02, FR-INT-03)
**Status:** ✅ Complete

This track gives IAMS its outside-the-walls connectivity: ERP systems (SAP / Oracle / Odoo) push `auditable_entity` and `finding` rows into IAMS via signed webhooks; HRIS and Active Directory targets receive `user` upserts back out when the IAMS user roster changes. Every delivery — inbound or outbound, accepted or rejected — lands in an audit-grade event ledger.

---

## What shipped

### Models ([migration 0021](../iams-backend/iams/migrations/0021_integrations_phase6.py))

| Model / Field | Purpose |
|---|---|
| `IntegrationSource` | Registered external system with inbound + outbound config |
| `IntegrationEvent` | Append-only ledger of every delivery (inbound/outbound × accepted/rejected/failed) |
| `Audit.external_source` / `external_id` | Idempotency key for inbound audits |
| `AuditableEntity.external_source` / `external_id` | Idempotency key for inbound entities |
| `Finding.external_source` / `external_id` | Idempotency key for inbound findings |

Partial unique constraints on `(external_source, external_id)` (with `external_id != ""`) prevent duplicate rows from a re-delivered webhook.

### Service module ([`iams/integrations.py`](../iams-backend/iams/integrations.py))

**HMAC** — `compute_signature(secret, body) → "sha256=<hex>"`, `verify_signature(secret, body, header_value)` using `hmac.compare_digest` (constant-time).

**Inbound importers** — both idempotent `update_or_create` keyed on `(external_source, external_id)`:

- `ingest_auditable_entity(source, payload)` — required fields: `external_id`, `name`, `department`.
- `ingest_finding(source, payload)` — required fields: `external_id`, `audit_external_id`, `title`, `severity`. Resolves the parent audit by external id; auto-creates the Audit row on the fly when `audit_title` is supplied (common ERP-driven pattern: audit materializes only once a finding lands).

Both validate **before** opening the `transaction.atomic()` block so a rejection event persists even when we raise `IngestError`.

**Outbound** — `push_user(source, user)` POSTs a narrow user payload (no password / MFA / lockout state) to `source.outbound_url` with both `Authorization: Bearer <token>` and the HMAC `X-IAMS-Signature` header so the receiving system can verify origin even behind a TLS-terminating proxy. `push_user_to_all_targets(user)` fans out across every active source with `outbound_pushes_users=True`.

### Endpoints

| Method | Path | Purpose | Auth |
|---|---|---|---|
| `POST` | `/api/integrations/webhooks/<source_id>/auditable-entities/` | Inbound entity ingest | HMAC-signed |
| `POST` | `/api/integrations/webhooks/<source_id>/findings/` | Inbound finding ingest | HMAC-signed |
| CRUD | `/api/integrations/sources/` | Manage external systems | `manage_settings` |
| `GET` | `/api/integrations/events/` | Read delivery ledger | `manage_settings` |

Webhook responses:

| Status | When |
|---|---|
| 201 | Created |
| 200 | Updated (idempotent re-post) |
| 400 (`payload_invalid`) | Required field missing / parent audit not resolvable |
| 401 (`signature_invalid`) | HMAC mismatch |
| 404 | Unknown `source_id`, source `inbound_enabled=false`, source paused, or unknown resource |

### Signal — User outbound fan-out

`post_save` on `User` calls `push_user_to_all_targets(user)`. Wrapped in try/except so a network failure can't break user creation. Failures land as `IntegrationEvent(direction=outbound, status=failed)` rows for retry.

### Frontend ([`src/lib/integrations-api.ts`](../iams-frontend/src/lib/integrations-api.ts))

Admin-grade typed CRUD + event ledger read with `{sourceId?, direction?, status?}` filters. The discriminated `IntegrationKind` union prevents typos in source kind. `inbound_secret` / `outbound_token` are write-only — never round-trip through the FE.

---

## Tests

**631/631 passing** (was 606; +25 new integration tests).

Coverage breakdown:

- **HMAC** (4): round-trip, tampered body, wrong secret, empty inputs.
- **Inbound entity** (4): create new, idempotency, mutable-field update, missing-field rejection with event persisted.
- **Inbound finding** (3): parent-audit-unknown rejection, auto-create audit, idempotent upsert.
- **Webhook endpoint** (6): bad signature, unknown resource, unknown source, valid payload, disabled source, invalid payload.
- **Outbound** (4): successful push, HTTP failure recorded, network exception recorded, fan-out skips paused sources.
- **Signal** (1): user save triggers fan-out.
- **REST surface** (3): admin-only, secrets omitted from response, event-ledger filters.

---

## Decisions

- **Mutual HMAC, not one-way.** Outbound posts ship *both* a bearer token and an HMAC signature. The bearer authenticates IAMS to the receiver; the HMAC lets the receiver verify the body hasn't been tampered with even if a downstream proxy re-signs the TLS connection. Defense in depth.
- **`update_or_create` for idempotency, not "ignore if exists".** Re-delivering a webhook should refresh the row (severity might have changed, owner might have rotated). Idempotency means "same payload → same end state," not "first wins."
- **Reject *and* record.** Required-field validation runs outside the atomic block so the rejection event still commits when we raise `IngestError`. Operator sees every malformed delivery in the ledger, not just successes.
- **No retry loop.** A failed outbound push records the event; retries are a Celery task pattern, not something the synchronous push function should own. Phase 7 (if there's a retry SLA) is the place to wire that up.
- **Webhook responses use the same `code` taxonomy as the auth endpoints.** `signature_invalid`, `payload_invalid` — consistent vocab across the API.
- **Audit gets external columns too.** Findings refer to their parent audit by `audit_external_id` from inbound payloads; the Audit table needs the same provenance keys to support that lookup and the on-the-fly audit creation path.

---

## What's deferred to operator

- Setting up the `IntegrationSource` rows + their secrets in the admin or via REST.
- Configuring the ERP/HRIS systems to call the webhook endpoint with the right HMAC.
- Retry policy (the failed events are visible; the operator decides whether to re-deliver from the source or trigger a backend re-push).

---

## What's next in Phase 6

| Track | Title | Status |
|---|---|---|
| 1 | SSO via Keycloak | ✅ Complete |
| 2 | **ERP / HR Integrations** | ✅ Complete |
| 3 | Accessibility & i18n | ⏳ Next |
| 4 | Documentation & Training | ⏳ |
