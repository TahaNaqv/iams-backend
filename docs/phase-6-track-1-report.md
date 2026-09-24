# Phase 6 Track 1 — Keycloak / OIDC SSO (Complete)

**Date:** 2026-05-13
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 6 Track 1 (FR-UAM-05, FR-INT-05)
**Status:** ✅ Complete

This track wires IAMS into corporate Active Directory via Keycloak as the OIDC IdP. Users sign in with their AD credentials once at Keycloak; IAMS JIT-provisions a `User` + `UserProfile` on first login and re-syncs the role from the Keycloak group claim on every subsequent sign-in. Password authentication for service / break-glass accounts keeps working — SSO is additive, not exclusive.

---

## What shipped

### Model + migration

`KeycloakGroupRoleMap` ([migration 0020](../iams-backend/iams/migrations/0020_sso_phase6.py)):

| Column | Purpose |
|---|---|
| `group_name` | Full Keycloak group path, e.g. `/IAMS/Auditors`. Unique. |
| `role` | FK → `Role`. Protected (can't delete a mapped role). |
| `precedence` | Lower wins when a user is in multiple groups. |
| `is_active` | Soft disable without losing the row. |

### Service module (`iams/sso.py`)

- `sso_enabled()` — True iff `IAMS_SSO_ENABLED=True` *and* the OIDC endpoints are configured. Both gates required so a half-set env doesn't 500 the discovery endpoint.
- `sso_config_payload()` — the JSON the FE login page consumes.
- `IAMSOIDCAuthenticationBackend(OIDCAuthenticationBackend)`:
  - `create_user(claims)` — JIT provisions a fresh `User` + `UserProfile`. Role from group claim (`resolve_role_from_groups`) or `IAMS_SSO_DEFAULT_ROLE` ("Viewer", auto-created if absent). Unusable password — SSO users can never password-log-in.
  - `update_user(user, claims)` — re-syncs role from groups every sign-in, stamps `last_login_at` + `last_activity_at`.
  - `filter_users_by_claims(claims)` — matches by `preferred_username` → `email` (case-insensitive).

### Endpoints

| Method | Path | Purpose | Auth |
|---|---|---|---|
| `GET` | `/api/auth/sso/config/` | Discovery for the FE login page | public |
| `GET` | `/api/auth/sso/login/?return_to=…` | 302 to Keycloak | public |
| `GET` | `/api/auth/sso/callback/` | OIDC code exchange → mint JWTs → redirect to FE | public |
| `GET/POST/PATCH/DELETE` | `/api/sso/group-role-maps/` | Admin: manage group→role mappings | `manage_roles` (read), `manage_settings` (write) |

### Flow

```
FE login page  ──GET /api/auth/sso/config/────▶  IAMS BE
              ◀──{enabled, providerName, loginUrl}

[user clicks "Sign in with corporate account"]
              ──GET /api/auth/sso/login/?return_to=/audits─▶  IAMS BE
                                                  302 ──▶  Keycloak
[Keycloak authenticates user via AD federation + (optional) MFA]
                                       302 with ?code=…&state=… ──▶  /api/auth/sso/callback/
              ◀───────────────────────  302 to FE with #access=…&refresh=…&return_to=/audits
FE /login/sso/callback parses fragment, persists tokens, navigates to return_to.
```

### Settings (env-driven)

```env
IAMS_SSO_ENABLED=true
IAMS_SSO_PROVIDER_NAME=Corporate SSO
IAMS_SSO_DEFAULT_ROLE=Viewer
IAMS_SSO_TRUSTS_IDP_MFA=true

OIDC_RP_CLIENT_ID=iams-backend
OIDC_RP_CLIENT_SECRET=...
OIDC_OP_AUTHORIZATION_ENDPOINT=https://keycloak.iams.internal/realms/iams/protocol/openid-connect/auth
OIDC_OP_TOKEN_ENDPOINT=https://keycloak.iams.internal/realms/iams/protocol/openid-connect/token
OIDC_OP_USER_ENDPOINT=https://keycloak.iams.internal/realms/iams/protocol/openid-connect/userinfo
OIDC_OP_JWKS_ENDPOINT=https://keycloak.iams.internal/realms/iams/protocol/openid-connect/certs
OIDC_OP_LOGOUT_ENDPOINT=https://keycloak.iams.internal/realms/iams/protocol/openid-connect/logout
OIDC_RP_SIGN_ALGO=RS256
OIDC_RP_SCOPES=openid email profile groups
```

### Frontend ([`src/lib/sso-api.ts`](../iams-frontend/src/lib/sso-api.ts))

Strict-mode-clean. Public discovery falls back gracefully (a failed `/sso/config/` doesn't lock the password flow). `parseSSOCallbackFragment(...)` extracts the JWT pair + return path from the URL hash that the backend redirects to.

---

## Tests

**606/606 passing** (was 586; +20 new SSO tests).

Coverage:

- Discovery — disabled by default, enabled when fully configured, endpoint shape (4).
- Login redirect — 503 when disabled, 302 with correct query string when enabled (3).
- Callback — 503/disabled, missing code → 400, state mismatch → 400 (3).
- `resolve_role_from_groups` — no match, precedence wins, inactive filtered (3).
- JIT provisioning — default role, group-mapped role, re-sync on subsequent login, case-insensitive email match (4).
- Admin REST surface — read needs `manage_roles`, write needs `manage_settings`, create succeeds with correct payload (3).
- Password login still works when SSO is enabled (1).

---

## Decisions

- **Mint our own SimpleJWT after OIDC code exchange.** The rest of the API stack is JWT-authed; pretending Keycloak's tokens are good enough would force a Bearer-token-introspection middleware. Re-mint at the SSO boundary, keep the downstream code path identical.
- **JIT-provisioned users get `set_unusable_password()`.** SSO is the only path to log them in. If SSO is later disabled, the user must be re-provisioned via SSO or have a password set by an admin — no surprise password access.
- **Group → role mapping table is operator-managed, not group-name-heuristic.** A group called `/IAMS/Auditors` matters only because a row says it maps to the Auditor role. No magic string parsing — explicit > implicit.
- **`resolve_role_from_groups` returns `None` for no match.** Caller falls back to `IAMS_SSO_DEFAULT_ROLE` (Viewer). A user with no group mapping logs in but lands in a read-mostly role — admin must deliberately wire in the privilege.
- **SSO endpoints are public + authentication_classes=[] but state-protected.** Standard OAuth/OIDC requirement: the `state` parameter is generated in the session at login and checked on callback. State mismatch → 400.

---

## What's deferred to operator

- Stand up Keycloak instance + create the `iams` realm + `iams-backend` client.
- AD/LDAP federation on Keycloak side.
- Set the OIDC_* env vars on the IAMS deployment.
- Create the initial `KeycloakGroupRoleMap` rows in Django admin (or via the new REST endpoint).

---

## What's next in Phase 6

| Track | Title | Status |
|---|---|---|
| 1 | SSO via Keycloak | ✅ Complete |
| 2 | ERP / HR integrations | ⏳ Next |
| 3 | Accessibility & i18n | ⏳ |
| 4 | Documentation & Training | ⏳ |
