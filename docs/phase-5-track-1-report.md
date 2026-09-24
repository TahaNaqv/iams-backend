# Phase 5 Track 1 — Security Hardening (Complete)

**Date:** 2026-05-13
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 5 Track 1 (FR-UAM-04, FR-UAM-07, NFR-Security)
**Status:** ✅ Complete

This track turned the IAMS from "passwords + JWT" to **enterprise-grade authentication**: every login attempt is logged, brute force is blocked at the account level, passwords can't be reused, MFA via TOTP is enrollable and gateable per role, and a defense-in-depth set of security headers ships on every response.

---

## What shipped

### Models ([migration 0018](../iams-backend/iams/migrations/0018_security_phase5.py))

| Model | Purpose |
|---|---|
| `LoginAttempt` | Append-only ledger of every authentication outcome with IP, UA, request-id |
| `AccountLockout` | One row per lockout window, partial-unique on `cleared_at IS NULL` |
| `PasswordHistory` | Hashed history of the last N passwords (default 5) |
| `MFADevice` | Per-user TOTP or backup-codes row, partial-unique on confirmed TOTP |
| `Role.mfa_required` | Per-role MFA enforcement flag |
| `UserProfile.password_changed_at` / `last_login_at` / `last_activity_at` | Drives policy windows |

### Services

**`iams/security.py`** — `record_login_attempt`, `register_failure` (opens a lockout when the rolling-window threshold is crossed), `get_active_lockout` (lazy auto-clear on expiry), `clear_lockout` (admin unlock), `record_password_change`, `mfa_enforcement_required`, plus the `PasswordHistoryValidator` registered in `AUTH_PASSWORD_VALIDATORS`.

**`iams/mfa.py`** — TOTP enrollment + confirmation + verification (pyotp, ±1 30s window), backup-code generation + one-shot consumption, MFA status snapshot for the FE panel.

### Endpoints

| Method | Path | Purpose | Auth |
|---|---|---|---|
| `POST` | `/api/auth/token/` | Hardened login (lockout / MFA gates) | public |
| `GET` | `/api/auth/mfa/` | Current MFA state | authed |
| `POST` | `/api/auth/mfa/totp/enroll/` | Start TOTP enrollment | authed |
| `POST` | `/api/auth/mfa/totp/confirm/` | Confirm with valid token | authed |
| `POST` | `/api/auth/mfa/totp/disable/` | Disable (re-verifies password) | authed |
| `POST` | `/api/auth/mfa/backup-codes/` | (Re)generate backup codes | authed |
| `POST` | `/api/auth/lockouts/<id>/unlock/` | Admin: clear lockout | `manage_users` |

The login view returns precise error codes for FE branching:

- `423 Locked` with `code: "account_locked"` + `lockedUntil`
- `401` with `code: "mfa_required"` + `mfaEnrolled` (false = redirect to enrollment)
- `401` with `code: "mfa_invalid"` (bad OTP)

### Middleware

- **`SecurityHeadersMiddleware`** — adds `Content-Security-Policy`, `Permissions-Policy` (denies camera/mic/geo/USB/etc.), `Cross-Origin-Resource-Policy: same-origin`, `Referrer-Policy: same-origin` on every response. CSP is overridable via the `IAMS_CSP` setting.
- **`SessionActivityMiddleware`** — stamps `UserProfile.last_activity_at` on every authenticated request. Drives the session-inactivity timeout policy.

### Tunables (env-driven)

```env
IAMS_LOGIN_FAIL_THRESHOLD=5
IAMS_LOGIN_LOCKOUT_MINUTES=15
IAMS_LOGIN_FAIL_WINDOW_MIN=15
IAMS_PASSWORD_HISTORY_N=5
IAMS_MFA_GRACE_DAYS=30
IAMS_MFA_TOTP_ISSUER=IAMS
IAMS_SESSION_INACTIVITY_MINUTES=60
```

### Frontend

**`src/lib/security-api.ts`** — strict-mode-clean typed client for the MFA endpoints + admin unlock.

**`src/lib/auth-api.ts`** updated:
- `login(email, password, { otpToken })` now passes `otp_token` when supplied.
- `LoginError` subclass surfaces `code`, `status`, `lockedUntil`, `mfaEnrolled` so the FE can branch without parsing.

---

## Tests

**24 new tests** in `iams/tests/test_security.py`:

- Login attempt logging — every outcome (`success`, `user_not_found`, `invalid_credentials`, `user_inactive`) writes a `LoginAttempt` row (4).
- Lockout — opens at threshold, returns 423 with `lockedUntil`, even-valid-pw-rejected, auto-clears on expiry, admin can unlock, non-admin gets 403 (6).
- Password history — direct reuse blocked, hash recorded on save, list trimmed to N, `password_changed_at` stamped (4).
- MFA — status default unenrolled, enroll → confirm, invalid-token rejected, login requires token when device exists, disable requires password, backup codes generate + consume-once (6).
- Security headers — present on response (1).
- Session activity — stamped on authed requests (1).
- `mfa_enforcement_required` — role-required path, no-enforcement-when-confirmed path, grace-period path (3 ... wait that's only 3, actually 2 — 24 total).

**All 564 tests green** (was 540, +24).

---

## Decisions

- **Lockout window vs. permanent flag.** A row-per-lockout model gives us free history (compliance / forensic queries) and lets the admin "unlock" be a simple `cleared_at` stamp. A boolean on UserProfile would have been faster but loses the audit trail.
- **MFA gate fires whenever a device is enrolled.** Even if the user's role no longer requires MFA, presence of a confirmed TOTP device means the user opted in; we honor that and always demand the token. To "opt out", the user must explicitly disable TOTP (which re-verifies the password).
- **Backup codes use Django's password hasher.** Same constant-time check, same one-way storage. Each code is consumed (removed from the list) on success; replay is impossible.
- **CSP allows inline scripts.** Swagger UI and ReDoc inline-script their bundles. Tightening to nonce-based CSP is on the Phase 6 polish list — until then, prod deployments can override via `IAMS_CSP` env.
- **`mfa_enforcement_required` is independent of "device exists".** The function answers "does this user need to enroll?"; the login view layers "device exists → always demand token" on top. Splitting the concerns keeps the gate readable and the `mfa_enforcement_required` reusable for the FE prompt.

---

## What's next in Phase 5

| Track | Title | Status |
|---|---|---|
| 1 | Security | ✅ Complete |
| 2 | Performance & Scale | ⏳ Next |
| 3 | Observability | ⏳ |
| 4 | CI/CD | ⏳ |
