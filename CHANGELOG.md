# Changelog

All notable changes to the IAMS Django REST API backend.

## [0.23.0] — Phase 6 Track 4: Documentation (2026-05-13)

### Added (repo-root)
- **`README.md`** — root entry point with quick links to every other doc, phase reports, run-local commands.
- **`docs/admin-guide.md`** — operator runbook covering architecture, the full env-var matrix (across all 22 settings the project has accumulated), initial deployment, day-2 operations, Keycloak SSO setup, ERP / HR integration wiring, backup + restore, monitoring + alerting, and troubleshooting.
- **`docs/user-guide.md`** — end-user documentation by role: auditors, audit managers, auditees, executives / audit committee. Covers MFA enrollment, working papers, CAP response, CSA, language switching.
- **`docs/api-reference.md`** — narrative API docs that complement the auto-generated OpenAPI schema: conventions (camelCase JSON), auth flow, pagination envelope, the curated error-code taxonomy, every domain endpoint group with a one-paragraph orientation, rate limiting, and how to generate typed clients via `openapi-typescript` / `openapi-generator`.
- **`docs/training-scripts/`** — five video scripts (`01-intro`, `02-auditor`, `03-manager`, `04-auditee`, `05-admin`) structured as time/narration/on-screen tables so a producer can record straight through.

### Notes
- No code changes this track. Backend tests unchanged at **637 passing**.
- The docs deliberately point back into the per-phase reports in `docs/phase-N-track-M-report.md` for the design rationale; the guides are the *how*, the reports are the *why*.
- Project status: **Phase 6 closed out. Production-shippable.** Ongoing work is operational.

## [0.22.0] — Phase 6 Track 3: i18n preference (2026-05-13)

### Added
- **`UserProfile.language`** field ([migration 0022](iams/migrations/0022_i18n_phase6.py)) with choices `en | ar | fr`, default `en`. The FE reads this on bootstrap to restore the user's preferred locale across browsers / devices.
- `MeSerializer` now surfaces `language`; `MeUpdateSerializer` accepts a `language` write-only field and applies it to `user.profile.language` in `update()`. RBAC unchanged — language is a self-edit, not a privilege.
- **6 new tests** in `iams/tests/test_i18n.py` — default value, GET /me/ shape, PATCH happy-path for both `ar` and `fr`, unsupported language rejection (400), persistence across an unrelated field update.

### Notes
- **Backend tests: 637 passing** (was 631; added 6).
- Server-side message translation (Django gettext) is deliberately deferred — every error string the FE renders is keyed by a stable `code` (e.g. `signature_invalid`, `mfa_required`) and the FE translates locally. That keeps the backend lean and avoids the deploy churn that comes with each new locale.

## [0.21.0] — Phase 6 Track 2: ERP / HR Integrations (2026-05-13)

### Added
- **Two new models + 6 column additions** ([migration 0021](iams/migrations/0021_integrations_phase6.py)):
  - `IntegrationSource` — registered external system (SAP / Oracle / Odoo / AD / HRIS / generic). Tracks `inbound_enabled` + `inbound_secret` (HMAC-SHA256 shared secret), `outbound_enabled` + `outbound_url` + `outbound_token` + `outbound_pushes_users`, `status`, `last_inbound_at` / `last_outbound_at` / `last_error`.
  - `IntegrationEvent` — append-only ledger of every inbound and outbound exchange (`direction`, `resource_type`, `external_id`, `status` ∈ accepted/rejected/failed, `error`, `payload`). Indexes on `(source, -timestamp)` and `(resource_type, external_id)` for forensic queries.
  - `external_source` + `external_id` columns on `Audit`, `AuditableEntity`, `Finding` with partial unique constraints — idempotent upserts key off `(external_source, external_id)`.
- **`iams.integrations` service module**:
  - **HMAC**: `compute_signature(secret, body)` produces `sha256=<hex>`; `verify_signature(...)` uses `hmac.compare_digest` for constant-time comparison.
  - **Inbound**: `ingest_auditable_entity(source, payload)` and `ingest_finding(source, payload)` — both idempotent `update_or_create` keyed on `(external_source, external_id)`. Required-field validation runs *outside* the atomic block so rejection events persist even on failure. The finding importer auto-creates the parent Audit when `audit_title` is supplied (ERP-driven workflow: audit only materializes once a finding lands).
  - **Outbound**: `push_user(source, user)` POSTs the user payload (narrow shape — no password / MFA / lockout state) with HMAC-SHA256 signature header + bearer token. Network failures, HTTP non-2xx, and successes are all rowed in `IntegrationEvent`. `push_user_to_all_targets(user)` fans out to every active source with `outbound_pushes_users=True`.
- **Webhook endpoint** at `POST /api/integrations/webhooks/<source_id>/<resource>/` — public-but-HMAC-signed. `X-IAMS-Signature: sha256=<hex>` header required; mismatch → 401. Resource ∈ `auditable-entities` / `findings`. Returns 201 on create, 200 on update, 400 on invalid payload (with `code: payload_invalid`), 401 on signature mismatch (with `code: signature_invalid`), 404 on unknown source / resource.
- **REST surface** at `/api/integrations/sources/` (full CRUD) and `/api/integrations/events/` (read-only with `?source_id=`, `?direction=`, `?status=` filters). Both gated by `manage_settings`. Secrets (`inbound_secret`, `outbound_token`) are write-only — never echoed back to the FE.
- **Signal handler**: `post_save` on `User` triggers `push_user_to_all_targets(user)` so every new / updated user is pushed to every outbound-enabled HRIS / AD target. Wrapped in try/except so a network failure can't break user creation.
- **25 new tests** in `iams/tests/test_integrations.py` — HMAC round-trip + tamper resistance + constant-time, idempotent entity ingest, auto-create audit from finding payload, parent-audit-missing error path, all 6 webhook 4xx/5xx code paths, mocked outbound push (success / HTTP failure / network exception), signal fan-out (paused source skipped), admin-only REST + secret omission from response, event-ledger filtering.

### Dependencies
- Already present: `requests` (used by outbound HTTP push).

### Notes
- **Backend tests: 631 passing** (was 606; added 25).
- The integration boundary is **trust-by-shared-secret** on both sides: inbound webhooks must HMAC-sign with `inbound_secret`, outbound posts include both a bearer token (RFC 6750) AND an HMAC signature of the body so the receiving system can verify origin even when TLS terminates early at a proxy.
- Rejection-and-failure events keep working even on validation errors: required-field checks run before any `transaction.atomic()` so the `IntegrationEvent(status=rejected)` row persists. The operator sees every malformed delivery in the admin ledger, not just the successful ones.
- The user-outbound signal handler swallows exceptions — observability + integration must never break user provisioning. Failures are logged and rowed as `IntegrationEvent(status=failed)` for retry.

## [0.20.0] — Phase 6 Track 1: Keycloak / OIDC SSO (2026-05-13)

### Added
- **`KeycloakGroupRoleMap` model** ([migration 0020](iams/migrations/0020_sso_phase6.py)) — maps a Keycloak group path (e.g. `/IAMS/Auditors`) to an IAMS `Role`. Precedence-ordered (lower wins) so a user in multiple mapped groups deterministically picks one role. `is_active` flag for transient disabling.
- **`iams.sso` service module**:
  - `sso_enabled()` — True iff `IAMS_SSO_ENABLED=True` *and* the OIDC endpoints are configured.
  - `sso_config_payload()` — payload returned by `/api/auth/sso/config/` for the FE login page.
  - `build_sso_redirect_url(...)`, `mint_jwt_pair(...)` — server-side SSO orchestration helpers.
  - `resolve_role_from_groups(groups)` — picks the highest-precedence Role matching the user's group claim.
  - `IAMSOIDCAuthenticationBackend` (subclass of `mozilla_django_oidc.auth.OIDCAuthenticationBackend`) with:
    - `create_user(claims)` — JIT provisions a fresh User + UserProfile, role from group mapping or `IAMS_SSO_DEFAULT_ROLE` (auto-creates "Viewer" if absent), unusable password (never lets SSO users password-log-in).
    - `update_user(user, claims)` — re-syncs role from group claim on every sign-in, stamps `last_login_at` / `last_activity_at`.
    - `filter_users_by_claims(claims)` — matches by `preferred_username` → `email` (case-insensitive).
- **3 new SSO endpoints**:
  - `GET /api/auth/sso/config/` — public discovery; FE login page reads this to decide whether to show the SSO button.
  - `GET /api/auth/sso/login/?return_to=…` — server-side 302 to Keycloak with PKCE state in the session.
  - `GET /api/auth/sso/callback/` — exchanges the auth code, runs `IAMSOIDCAuthenticationBackend.authenticate()`, mints a SimpleJWT pair, and redirects the browser to `${FE}/login/sso/callback#access=…&refresh=…&return_to=…`. Audit-log captures `sso_login`.
- **Admin REST surface** for the group→role mapping table at `/api/sso/group-role-maps/`:
  - Read: `manage_roles` (so role admins can see what's wired).
  - Write: `manage_settings` (changing a mapping effectively grants/revokes access on the next SSO sign-in).
- **Settings & auth backend chain**:
  - `AUTHENTICATION_BACKENDS = ["iams.sso.IAMSOIDCAuthenticationBackend", "django.contrib.auth.backends.ModelBackend"]`. Password login keeps working (additive, not exclusive).
  - 9 new env-driven settings: `IAMS_SSO_ENABLED`, `IAMS_SSO_PROVIDER_NAME`, `IAMS_SSO_DEFAULT_ROLE`, `IAMS_SSO_TRUSTS_IDP_MFA`, plus the standard `OIDC_*` block.
- **20 new tests** in `iams/tests/test_sso.py` — discovery (disabled by default / enabled-when-configured / endpoints-must-be-set / config endpoint shape), login redirect (503 when disabled / 302 with correct query string when enabled), callback (503 / missing code / state mismatch), `resolve_role_from_groups` (no match / precedence / inactive filter), JIT provisioning (default role / group-driven role / re-sync on subsequent login / case-insensitive email match), admin REST surface (RBAC + create-with-payload), password coexistence with SSO enabled.

### Dependencies
- Added: `mozilla-django-oidc` 5.0+ as the OIDC client. `mozilla_django_oidc` added to `INSTALLED_APPS`.

### Notes
- **Backend tests: 606 passing** (was 586; added 20).
- SSO is **opt-in** at runtime: `IAMS_SSO_ENABLED=False` (default) keeps every SSO endpoint returning 503 and the login page falls back to password login.
- The OIDC backend writes an unusable password on JIT-provisioned users so they can't be password-authed even if `IAMS_SSO_ENABLED` is later turned off — they must be re-authenticated via SSO or have a password set by an admin.
- We mint our own SimpleJWT tokens after a successful OIDC code exchange instead of trusting Keycloak's access token end-to-end. The downstream API path stays unchanged (same JWT auth, same throttling, same refresh).

## [0.19.0] — Phase 5 Track 4: CI/CD (2026-05-13)

### Added (repo-root)
- **`.github/workflows/ci.yml`** rewritten — three parallel jobs:
  - `backend`: `uv sync` → ruff (soft) → `makemigrations --check --dry-run` (fails on missing migrations) → pytest with coverage → coverage artifact.
  - `frontend`: `npm ci` → `tsc --noEmit` → lint (soft) → `npm run build` → dist artifact.
  - `contract`: exports the OpenAPI schema via `manage.py spectacular` and uploads it as an artifact.
  - `concurrency: cancel-in-progress` on the same branch — CI cost discipline.
- **`.github/workflows/release.yml`** — image build + Trivy scan + blue-green deploy pipeline:
  - Builds backend + frontend images, tags with `sha-{12-char-sha}` or the git tag.
  - Pushes to the configured registry (defaults to `harbor.iams.internal`).
  - Trivy scans both images for `CRITICAL,HIGH` vulns; fails the build on findings (`ignore-unfixed: true`).
  - Auto-deploys to staging on `main` pushes; manual or tag-driven promotion to production via the protected `production` environment.
- **`docker-compose.yml`** — full-stack topology with `blue` / `green` profiles for backend + frontend, plus shared Postgres, pgbouncer, Redis, MinIO, ClamAV, Celery worker + beat, and nginx. Health-checks on every long-lived service.
- **`iams-frontend/Dockerfile`** + **`iams-frontend/nginx.conf`** + **`iams-frontend/.dockerignore`** — multi-stage build (Vite → `nginx:alpine`); SPA-friendly history routing; aggressive caching on hashed `/assets/` (`max-age=1y, immutable`); short cache on favicons / robots; no-cache on `index.html`; container-internal `/healthz`.
- **`deploy/blue_green.sh`** — atomic blue-green orchestration:
  1. Reads the current live color (`/opt/iams/current-color`).
  2. Pulls images + runs `manage.py migrate` inside the **new** color's container *before* the swap (a broken migration aborts the deploy with the old color still live).
  3. Waits up to `HEALTH_TIMEOUT_S` for `/ready/` on the new color.
  4. Swaps the nginx upstream symlink + `nginx -s reload`.
  5. 30s drain grace before stopping the old color. Idempotent; safe to re-run.
- **`deploy/smoke_test.sh`** — post-deploy curl-based check (`/health/`, `/ready/`, `/metrics`, `/api/schema/`, FE `/`, `/api/audits/` returns 401). Fails the deploy if any check is wrong.
- **`deploy/nginx/`** — `iams.conf` (TLS-terminating reverse proxy) + `upstream-blue.conf` / `upstream-green.conf` (one-symlink-flip color swap).
- **`deploy/backup.sh`** — nightly `pg_dump` (custom format) + MinIO `mc mirror`, encrypted with `age` (multi-recipient), shipped via `restic` to NAS + optional offsite repo. Retention: 7 daily / 4 weekly / 12 monthly. Verifies dump readability before encrypting.
- **`deploy/restore.sh`** — counterpart for the quarterly restore drill: `restic restore` → `age -d` → `pg_restore` into a target DB URL.
- **`MIGRATION-CHECKLIST.md`** at repo root — the N-1 rule, safe patterns for adding NOT NULL columns, renaming columns, concurrent index creation, deleting models, data migrations with `reverse_code`, partial unique constraints, and the rollback procedure. CI's `makemigrations --check` is the auto-gate; this checklist is the rest.

### Notes
- **Backend tests: 586 passing** (Track 4 is process/infra, no new tests).
- Test count, model count, and migration count are unchanged from Track 3 (this track only adds CI / deploy / docker / docs).
- The deploy pipeline is **fail-closed**: a broken migration, failing Trivy scan, failing `/ready/` health check, or failing smoke test all leave the old color serving production traffic. No "fail forward" automation — operator decides whether to roll forward or back.
- Registry push (and therefore staging/prod deploy) is gated on `secrets.REGISTRY_USERNAME` being set. PRs build images locally for scanning but don't push, so forks can run the full pipeline without credentials.

## [0.18.0] — Phase 5 Track 3: Observability (2026-05-13)

### Added
- **`iams/logging.py` JsonFormatter** — every log record renders as one line of JSON with `time / level / logger / message / request_id / service / host / env / exception` plus any user-supplied `extra={}` keys folded in (non-serializable values are `repr`'d, never crash the log call). Wired into `LOGGING` as the default formatter; `LOG_FORMAT=text` env switches back to plain text for local dev. Promtail can ship straight to Loki without parsing.
- **`iams/metrics.py` Prometheus counters/gauges** for business events (NFR-Observability):
  - Counters: `iams_audits_created_total{department}`, `iams_audits_completed_total{department}`, `iams_findings_raised_total{severity}`, `iams_caps_created_total`, `iams_caps_closed_total`, `iams_approvals_requested_total{type}`, `iams_approvals_approved_total{type}`, `iams_approvals_rejected_total{type}`, `iams_login_attempts_total{outcome}`, `iams_account_lockouts_total{reason}`, `iams_report_jobs_total{kind}`, `iams_report_jobs_completed_total{kind}`, `iams_report_jobs_failed_total{kind}`.
  - Gauges: `iams_caps_overdue_current`, `iams_approvals_pending_current`.
  - `refresh_business_gauges()` syncs the gauges from the DB; called by the existing 5-minute `dashboards.refresh_caches` beat task so gauges stay accurate even if a process restart drops a signal.
- **Signal-driven metric increments** — six new `pre_save` / `post_save` handlers in `iams/signals.py` capture status transitions (created → completed, → approved, → rejected, → closed) and bump the right counter. All wrapped in `_safe_metric` so observability can't break the request path. Login-attempt + lockout counters wired in `iams/security.py`; report-job counters in `iams/tasks/reports.py`.
- **`iams/telemetry.py` OpenTelemetry SDK bootstrap** — initializes the tracer provider + OTLP HTTP exporter + auto-instruments Django, Celery, Redis, and Psycopg2 when `OTEL_ENABLED=true`. Default sample rate 10% via `ParentBased(TraceIdRatioBased(0.1))`. Idempotent (safe to call from `IamsConfig.ready()` and any other entry point).
- **`deploy/grafana/`** — checked-in Grafana dashboards as JSON:
  - `iams-system.json`: request rate by status class, latency p50/p95/p99, error rate (with threshold colors), DB pool, Celery queue depth, login attempts, lockouts.
  - `iams-business.json`: overdue-CAPs gauge, approvals-pending gauge, daily findings by severity, audit lifecycle flow, CAP create/close flow, approval flow by type, report-job pass/fail by kind.
- **`deploy/prometheus/iams-alerts.yml`** — alert rules grouped into `iams.system` (5xx > 1% / p95 > 1s / Celery backlog / DB errors), `iams.security` (lockout burst / failed-login spike), and `iams.business` (overdue CAP threshold / report-job failure rate). `severity=page` routes to PagerDuty; `warn` to Slack.
- **`deploy/README.md`** — wiring summary + environment knobs (`LOG_FORMAT`, `OTEL_*`, `SENTRY_*`).
- **13 new tests** in `iams/tests/test_observability.py` — JSON formatter shape + request-id correlation + extras folding + non-serializable repr + exception traceback capture, business counters bump on signal (audits / findings / CAPs / approvals), login-attempt counter, gauge refresh syncs state, `/metrics` endpoint exposes custom counters.

### Dependencies
- Added: `opentelemetry-sdk`, `opentelemetry-exporter-otlp`, `opentelemetry-instrumentation-django`, `opentelemetry-instrumentation-celery`, `opentelemetry-instrumentation-redis`, `opentelemetry-instrumentation-psycopg2`.

### Notes
- **Backend tests: 586 passing** (was 573; added 13).
- Cardinality discipline: metrics only label by bounded enums (status / severity / outcome / kind / reason / type / department). No per-id labels.
- Gauges *and* counters: `iams_caps_overdue_current` is a point-in-time gauge (refreshed by beat task), not a counter. Counters answer "how many ever"; gauges answer "how many right now". Both feed different Grafana panels.

## [0.17.0] — Phase 5 Track 2: Performance & Scale (2026-05-13)

### Changed
- **Default page size dropped 100 → 25** (NFR-Performance, p95 < 500ms target). `DefaultPagination.page_size = 25`, `max_page_size = 200` (cap unchanged). Endpoints that need denser views pass `?page_size=…` up to 200.

### Added
- **Composite indexes on hot dashboard / overdue-scan paths** ([migration 0019](iams/migrations/0019_perf_indexes_phase5.py)):
  - `Audit`: `(department, status)`, `(start_date)`, `(lead_auditor)`
  - `Finding`: `(department, status)`, `(owner, status, due_date)`, `(severity, status)`, `(created_date)`
  - `CorrectiveAction`: `(department, status)`, `(owner, status, due_date)`, `(finding, status)`
- **N+1 fixes on the two GenericForeignKey-using endpoints**:
  - `NotificationViewSet` now `select_related("target_content_type")` — the FE bell polls this every 60s and the `get_targetType` serializer method previously fired a ContentType lookup per row.
  - `AuditLogViewSet` same fix.
- **Query-budget regression tests** in `iams/tests/test_performance.py` (9 tests) using Django's `CaptureQueriesContext`:
  - Pagination defaults + envelope shape + max_page_size cap.
  - List endpoints (notifications, audit-log, findings, CAPs, audits) all bounded ≤ 12 queries on 20-50 row pages.
  - Dashboard KPIs bounded on first call + verified cache cuts second-call budget to ≤ 8.
- **Locust load-test scenario** at `loadtests/locustfile.py` — 11 weighted tasks mirroring the FE polling pattern (dashboard KPIs + notifications bell at weight 10, list endpoints at 4-6, less-frequent surfaces lower). README documents target (`500 concurrent users, p95 < 500ms`), how to seed a load-test user, and how to interpret reports.

### Dependencies
- Added: `nplusone` (available for future runtime detection; tests use Django's built-in `CaptureQueriesContext` instead — clearer failure messages).
- Already present: `locust` 2.x.

### Notes
- **Backend tests: 573 passing** (was 564; added 9).
- Indexes are all additive — migration 0019 is forward-only with no data movement.
- The query budgets in `test_performance.py` deliberately have ≈2x slack on the current numbers. They flag N+1 regressions (one new per-row query in a 50-row list explodes the budget) but tolerate harmless changes (an extra auth query, a session-touch UPDATE).
- pgbouncer sidecar + nginx static-asset cache tuning are operator-side; the IAMS app side of Track 2 is complete.

## [0.16.0] — Phase 5 Track 1: Security Hardening (2026-05-13)

### Added
- **Four new models** ([migration 0018](iams/migrations/0018_security_phase5.py)) plus three field additions:
  - `LoginAttempt` (FR-UAM-07) — append-only ledger of every auth attempt (success / invalid_credentials / user_not_found / user_inactive / account_locked / mfa_required / mfa_failed / throttled) with IP, user-agent, and request-id correlation.
  - `AccountLockout` (FR-UAM-04) — one row per lockout window, partial-unique on `cleared_at IS NULL` so only one active lockout per user. Auto-clears on `locked_until` expiry; admin can clear via the unlock endpoint.
  - `PasswordHistory` — hashed history of the last N passwords (configurable, default 5). Powers the `PasswordHistoryValidator`.
  - `MFADevice` — per-user TOTP / backup-codes rows with partial-unique on `(kind=totp, confirmed=true)` so a user can only have one active authenticator app.
  - `Role.mfa_required` flag for per-role MFA enforcement.
  - `UserProfile.password_changed_at`, `last_login_at`, `last_activity_at` — driven by the login + session-activity flows.
- **`iams.security` service module** — `record_login_attempt`, `register_failure` (opens a lockout when the rolling-window threshold is crossed), `get_active_lockout` (with lazy auto-clear on expiry), `clear_lockout`, `record_password_change`, `mfa_enforcement_required`, plus the `PasswordHistoryValidator` (registered in `AUTH_PASSWORD_VALIDATORS`).
- **`iams.mfa` service module** — `generate_totp_secret`, `totp_provisioning_uri`, `verify_totp_token` (pyotp, ±1 window drift), `begin_totp_enrollment`, `confirm_totp_enrollment`, `generate_backup_codes` (10 codes × 10 alphanum chars, hashed with Django's hasher), `consume_backup_code` (one-shot consumption), `get_mfa_status`.
- **Hardened JWT login view** at `POST /api/auth/token/` (FR-UAM-04, FR-UAM-07): looks up user → checks active lockout → checks `is_active` → validates password → opens a lockout if the failure threshold is crossed → enforces MFA when a confirmed TOTP device exists or when policy requires enrollment → returns specific error codes (`account_locked` with `lockedUntil`, `mfa_required` with `mfaEnrolled`, `mfa_invalid`).
- **6 new auth endpoints**:
  - `GET /api/auth/mfa/` — MFA status snapshot
  - `POST /api/auth/mfa/totp/enroll/` — start enrollment (returns provisioning URI + secret)
  - `POST /api/auth/mfa/totp/confirm/` — confirm with a valid token
  - `POST /api/auth/mfa/totp/disable/` — re-verifies password before removal
  - `POST /api/auth/mfa/backup-codes/` — regenerate (replaces any prior set; shown once)
  - `POST /api/auth/lockouts/<user_id>/unlock/` — admin (`manage_users`) clears an active lockout
- **`iams.middleware.SecurityHeadersMiddleware`** adds `Content-Security-Policy` (configurable via `IAMS_CSP`), `Permissions-Policy` (deny camera/mic/geo/etc.), `Cross-Origin-Resource-Policy: same-origin`, and `Referrer-Policy: same-origin` to every response.
- **`iams.middleware.SessionActivityMiddleware`** stamps `UserProfile.last_activity_at` on every authenticated request (drives the session-inactivity policy).
- **6 new security tunables** (all env-driven):
  - `IAMS_LOGIN_FAIL_THRESHOLD` (5), `IAMS_LOGIN_LOCKOUT_MINUTES` (15), `IAMS_LOGIN_FAIL_WINDOW_MIN` (15)
  - `IAMS_PASSWORD_HISTORY_N` (5)
  - `IAMS_MFA_GRACE_DAYS` (30), `IAMS_MFA_TOTP_ISSUER` ("IAMS")
  - `IAMS_SESSION_INACTIVITY_MINUTES` (60)
- **24 new tests** in `iams/tests/test_security.py` — every login outcome → LoginAttempt row, threshold-based lockout (open / 423 with `lockedUntil` / valid-pw-still-rejected / auto-expiry / admin-unlock / non-admin-403), password history (reuse rejected / hash recorded / trimmed to N / `password_changed_at` stamped), MFA TOTP (status / enroll → confirm / invalid-token rejected / login requires token when enrolled / disable requires password / backup codes generate + consume-once), security headers present on response, session activity stamping, `mfa_enforcement_required` unit tests for role + grace-period paths.

### Dependencies
- Added: `pyotp` (RFC 6238 TOTP), `qrcode` (FE-side QR rendering — actual QR rendered from the provisioning URI).

### Notes
- **Backend tests: 564 passing** (was 540; added 24).
- `mfa_enforcement_required(user)` returns True when the user's role has `mfa_required=True` *or* the MFA grace period has elapsed since the last password change. The login view treats this independently of whether a device is already enrolled — if a device exists, the OTP is *always* required; if no device exists and enforcement is on, login is blocked with `mfa_required` so the FE prompts enrollment.
- Migrations are backward-compat: every new model is additive, every field is nullable or has a sensible default.
- The CSP allows `'unsafe-inline'` for inline scripts to keep Swagger UI / ReDoc usable. Production deployments may tighten this via `IAMS_CSP` env override; staging-grade hardening is left to the operator until the inline-removal sweep in Phase 6.

## [0.15.0] — Phase 4 Track 3: Dashboards Backend (2026-05-12)

### Added
- **`iams/dashboards.py` service module** (FR-DASH-01..11) — pure, cacheable aggregator functions that the dashboard endpoints call:
  - `core_kpis(period?, department?)` — open-audits / overdue-findings / pending-CAPs / CAP-completion-rate. Accepts `YYYY` or `YYYY-Qn` period and free-text department.
  - `trends(period="YoY"|"FY{N}", department?)` — 8-quarter rolling YoY (or 4-quarter FY) series with `findings / auditsCompleted / capsClosed` per bucket.
  - `risk_heatmap_by_department()` — current `EntityRiskScore` rows bucketed by department × {Critical ≥80, High 60–79, Medium 40–59, Low <40}. Returns `{categories, departments, cells}`.
  - `rating_summary(period?)` — three-way rollup across QAIP `rating_overall`, ICFR `auditor_assessment` conclusions, and CSA weak-flag/average score.
  - `recent_activity(limit)` — last N `AuditLogEntry` rows (live; not cached — auditors want freshness).
  - `upcoming_audits(limit, department?)` — `start_date >= today` ordered ASC.
  - `role_bundle(role, user_email?)` — pre-composed panels for **executive / manager / auditor / auditee**. Auditor and auditee bundles slice by `user_email` ownership (`my_open_findings`, `my_open_caps`, `my_csa_responses`).
  - `cache_or_compute(key, fn, ttl=45s)` — read-through Redis cache helper, degrades gracefully when Redis is down (`IGNORE_EXCEPTIONS=True`).
  - `invalidate_dashboard_cache()` — flushes the `iams:dashboard:*` namespace; called by the beat task and ad-hoc on settings changes.
- **6 new API endpoints** at `/api/dashboard/...` (FR-DASH-02..11), all cached:
  - `GET /api/dashboard/trends/?period=YoY|FY2026&department=…`
  - `GET /api/dashboard/risk-heatmap/`
  - `GET /api/dashboard/ratings/?period=…`
  - `GET /api/dashboard/activity/?limit=…` (uncached — live feed)
  - `GET /api/dashboard/upcoming-audits/?limit=…&department=…`
  - `GET /api/dashboard/role/<executive|manager|auditor|auditee>/` (per-user cache key when role is auditor/auditee)
  - Existing `GET /api/dashboard/kpis/` now routes through the service and accepts `?period=…&department=…`.
- **Celery beat task** `iams.dashboards.refresh_caches` registered on `crontab(minute="*/5")` — warms the common dashboard payloads after invalidation so the next FE poll hits a fresh cache.
- **5 additional PDF renderers** (registered in `RENDERERS`):
  - `DepartmentRiskProfileRenderer` (FR-RPT-04) — consumes `risk_heatmap_by_department`; optional `?department=` filter.
  - `OpenIssuesRenderer` (FR-RPT-05) — every non-closed `Finding` × non-closed `CorrectiveAction`, grouped.
  - `ICFRSummaryRenderer` (FR-ICFR-05) — wraps `iams.icfr.build_icfr_summary`.
  - `QAIPAnnualRenderer` (FR-QAIP-04) — mirrors the QAIP dashboard JSON into a print-ready document; `period` required.
  - `AuditCommitteePackRenderer` (FR-DASH-11) — the board-facing roll-up: executive KPIs + trends + risk heat-map + ratings + upcoming audits in one PDF.
  - Templates land in `iams/templates/iams/reports/` and extend the shared `_base.html` (severity/status pills, KPI tiles, page footer).
- **38 new tests** in `iams/tests/test_dashboards.py` — aggregator math (KPIs, trends, heat-map, ratings, activity, upcoming), period + department filter precision, role-bundle panel composition, auditor/auditee user-scoping, cache hit-vs-miss instrumentation, every new API endpoint, every new renderer's context + filter behavior, registry-coverage check, IAMS_DISABLE_PDF_RENDER round-trip.

### Notes
- **Backend tests: 540 passing** (was 502; added 38).
- The dashboard cache uses sha256-digested kwargs JSON for stable keys (`iams:dashboard:<prefix>:<hash16>`); collisions are theoretical but the TTL bound keeps the blast radius to 45s.
- Materialized views for the slowest aggregators (heat-map + YoY trends) are deferred to Phase 5 — the current cache layer holds well under expected load (≈60s FE polls × 4 roles × ~20 concurrent users).

## [0.14.0] — Phase 4 Track 2: Report Generation Engine (2026-05-12)

### Added
- **`ReportJob` model** ([migration 0017](iams/migrations/0017_reportjob.py)) — async report-generation request. Tracks `kind`, `output_format`, `parameters` (JSON), `requested_by`, `status` (pending/running/completed/failed), `output_file` (FileField → MinIO in prod), `file_size_kb`, `error`, lifecycle timestamps.
- **`iams/reports/` renderer package** with a base class and **7 registered renderers**:
  - PDF (WeasyPrint + Jinja templates with shared base, header/footer, page-numbered footer): `AuditSummaryRenderer`, `FindingTrendsRenderer`, `CAPStatusRenderer`, `AnnualPlanRenderer`
  - Excel (openpyxl): `FindingsExcelRenderer`, `CAPsExcelRenderer`, `TimeEntriesExcelRenderer`
- **Templates** at `iams/templates/iams/reports/` with shared `_base.html` (severity/status pills, KPI tiles, page footer with counter).
- **`IAMS_DISABLE_PDF_RENDER=1` escape hatch** — emit raw HTML instead of calling WeasyPrint when system libs (pango/cairo) are unavailable. Used by the test suite and dev machines without the libs installed.
- **`iams.reports.generate_report` Celery task** — dispatches to the right renderer via the `RENDERERS` registry, writes the file, flips status, and dispatches a `Notification.KIND_GENERIC` to the requester with a deep link (success or failure).
- **API**:
  - `POST /api/reports/generate/` — `{kind, title?, parameters?}` → 201 with the new `ReportJob`. Validates kind against the registry; 400 with `supportedKinds` on unknown.
  - `GET /api/reports/jobs/` — scoped to the caller unless they hold `manage_settings` (admin sees the org); filterable by `kind` and `status`.
  - `GET /api/reports/jobs/{id}/` — poll status.
  - `GET /api/reports/jobs/{id}/download/` — 409 while pending/running, 404 when failed (with `error` body), 200 with `{url, fileSizeKb}` when completed.
- **RBAC** — `view_reports` gates all read paths; **Excel exports additionally require `export_reports`** (organization-level data leaves the system).
- **Audit log** captures `report_job_created` with kind + params as `ACTION_EXPORT`.
- **26 new tests** in `iams/tests/test_reports.py` — every renderer's context, Jinja output, Excel header+rows, filter precision, registry coverage, job lifecycle, Celery dispatch + notification, unknown-kind handling, all download states (409 pending / 404 failed / 200 completed), Excel permission gate, list scoping, RBAC matrix.

### Notes
- Five additional canonical reports (Department Risk Profile, Open Issues, ICFR Summary, QAIP Annual, Audit Committee Pack) follow the same `BaseRenderer` pattern and can be added by subclassing + adding to `RENDERERS`. Track 3 (dashboards backend) provides their aggregator endpoints first.
- **Backend tests: 502 passing** (was 476; added 26).

## [0.13.0] — Phase 4 Track 1: Configurable Risk Engine (2026-05-12)

### Added
- **Four risk-engine models** ([migration 0016](iams/migrations/0016_riskfactor_riskscoringmodel_and_more.py)) — FR-RISK-01..10:
  - `RiskFactor` — catalog of rateable dimensions (code/name/scale_min/scale_max). DB-level check on `scale_max > scale_min`.
  - `RiskScoringModel` — name/version/formula bundle with `high_risk_threshold` + active-per-name partial unique. Three formulas: `weighted_sum`, `weighted_avg`, `multiplicative`.
  - `RiskFactorWeight` — through-table; per-model factor weight.
  - `EntityRiskScore` — append-only snapshot per `(entity, scoring_model)` with `is_current` partial-unique. Holds `factor_values` JSON + computed `composite_score` (0-100 normalized) + `rank` + `is_high_risk` flag.
- **`iams/risk_engine.py` service** (FR-RISK-02..05, 07-08):
  - `compute_composite(model, factor_values)` — formula-aware, range-validated, returns Decimal in 0..100.
  - `record_score(entity, model, factor_values, by_user)` — atomic snapshot + previous-row `is_current` flip + auto-bump `entity.risk_rating` to High when composite ≥ threshold (preserves Critical).
  - `recompute_ranks(model)` — dense ranking across current scores (ties share rank).
  - `heat_map(model)` — likelihood × impact bucketed grid with per-cell entity lists.
  - `generate_audit_plan_draft(model, year, top_n, requested_by)` — top-N entities → draft `ApprovalRequest` of type Audit Plan; the existing post_save signal auto-applies the chain template (FR-PLAN-01).
  - `recompute_all_scores_for_model(model)` — bulk re-snapshot after weight/formula edits.
- **API** at `/api/risk/{factors,models,factor-weights,scores}/` plus three top-level endpoints:
  - `POST /api/risk/scores/record/` — write a new snapshot (direct CRUD on `/scores/` returns 405 to enforce single-entry).
  - `GET /api/risk/heat-map/?scoring_model_id=…`
  - `POST /api/risk/generate-plan/` — `{scoringModelId, year, topN}` → 201 with the created ApprovalRequest.
  - `POST /api/risk/models/{id}/recompute/` — bulk re-snapshot.
- **RBAC** — reads gated by `view_audits`; writes by `manage_settings`; `generate-plan` by `create_audits`.
- **Audit log** captures `risk_score_recorded`, `risk_model_bulk_recompute`, `audit_plan_generated_from_risk` with structured details.
- **32 new tests** in `iams/tests/test_risk_engine.py` — all three formulas with edge cases, range validation, missing-factor errors, current-row flip, high-risk threshold + risk_rating bump + Critical preservation, dense ranking with ties, heat-map placement, plan-draft + chain auto-apply, recompute bulk, full API + RBAC matrix.

### Test totals
- **Backend: 476 passing** (was 444; added 32).

## [0.12.0] — Phase 3 Track 4: ICFR (2026-05-12)

### Added
- **Four ICFR models** ([migration 0015](iams/migrations/0015_control_controltest_and_more.py)) — FR-ICFR-01..05:
  - `Control` — catalog entry per AuditableEntity. Framework (SOX/COSO/COBIT/Custom), type (preventive/detective/corrective), nature (manual/automated/hybrid), frequency, assertion. Unique on (entity, control_id).
  - `ControlTest` — one per (control, period, test_type). **Dual conclusions** for FR-ICFR-04 segregation: `management_assessment` + `auditor_assessment`. Computed `conclusion` property prefers auditor.
  - `ControlException` — per-sample observation with severity + M2M to `EvidenceFile`.
  - `DeficiencyReport` — OneToOne with `ControlTest`. Three classifications (control_deficiency / significant_deficiency / material_weakness) + lifecycle (draft → open → remediating → closed).
- **`iams/icfr.py` service module**:
  - `record_test_result(test, by_user, role, conclusion, notes)` — writes the right side's assessment, advances status (mgmt → in_progress, auditor → completed), and auto-creates a draft `DeficiencyReport` when the auditor concludes `deficient`. Idempotent on repeated calls.
  - `open_deficiency(deficiency, by_user, classification, ...)` — promotes draft → open with the auditor's final classification.
  - `close_deficiency(deficiency, by_user, management_response)` — final closure with management response capture.
  - `build_icfr_summary(period=None)` — aggregator: controls-by-framework, tests-by-status, tests-by-conclusion, exceptions-by-severity, deficiencies-by-classification, **openMaterialWeaknesses** rollup, totals.
- **API** at `/api/icfr/{controls,tests,exceptions,deficiencies}/` + `/api/icfr/summary/`:
  - All endpoints gated by `view_audits`.
  - Custom actions: `POST /icfr/tests/{id}/record-result/`, `POST /icfr/deficiencies/{id}/open/`, `POST /icfr/deficiencies/{id}/close/`.
- **Audit-log** captures `icfr_test_result_recorded`, `icfr_deficiency_opened`, `icfr_deficiency_closed` with structured payloads.
- **23 new tests** in `iams/tests/test_icfr.py` covering uniqueness constraints, dual-conclusion logic, auto-deficiency on failure, lifecycle transitions, exception+evidence attachment, summary math, period filter, API record-result validation, RBAC.

### Test totals
- **Backend: 444 passing** (was 421; added 23).

## [0.11.0] — Phase 3 Track 3: Control Self-Assessment (CSA) (2026-05-12)

### Added
- **Four CSA models** ([migration 0014](iams/migrations/0014_csaanswer_csaquestion_csaquestionnaire_csaresponse.py)) — FR-CSA-01..05:
  - `CSAQuestionnaire` — title, framework (COSO/COBIT/ISO 27001/Custom), version, status (draft/active/archived), `weak_threshold` (configurable per questionnaire). Unique `(title, version)`.
  - `CSAQuestion` — four response types (`yes_no`, `scale_1_5`, `text`, `evidence_required`), optional `category` (design / operating effectiveness) for split scoring, `weight` (≥1), `order`.
  - `CSAResponse` — one per business unit. Status (draft/submitted/under_review/closed), computed `score_overall` + per-category `score_design` / `score_operating`, `is_weak` boolean, lifecycle timestamps.
  - `CSAAnswer` — one per (response, question) (unique). Carries `value`, optional `evidence_file` FK, and an embedded auditor-challenge thread (`challenge_status`, `challenge_note`, `challenged_by/at`, `resolution_note`, `resolved_by/at`).
- **`iams/csa.py` service module**:
  - `compute_scores(response)` — overall + per-category 0-100 score from `weight`-weighted answer fractions.
  - `submit_response(response, by_user)` — atomic: refuses non-draft / inactive questionnaire / empty response; computes scores; flips status; if `score_overall < weak_threshold` fires side effects.
  - `open_challenge(answer, by_user, note)` — auditor opens a challenge; moves parent to `under_review`.
  - `resolve_challenge(answer, by_user, note)` — closes the challenge; rolls parent back to `submitted` when no challenges remain.
  - `close_response(response, by_user)` — auditor closes; refuses while challenges open.
- **Weak-control side effects** (FR-CSA-04): dispatches `Notification.KIND_GENERIC` to every Audit Manager via `dispatch_to_role` AND best-effort bumps the linked `AuditableEntity.risk_rating` to `High` (won't downgrade `Critical`). Both side effects are exception-swallowed so a notification failure can't roll back the submit.
- **API** (gated by `view_audits` for reads, `manage_settings` for questionnaire writes; responses + answers are `IsAuthenticated`):
  - `/api/csa/questionnaires/`, `/api/csa/questions/`, `/api/csa/responses/`, `/api/csa/answers/`
  - `POST /api/csa/responses/{id}/submit/` — locks + scores + fires weak-control signals
  - `POST /api/csa/responses/{id}/close/`
  - `POST /api/csa/answers/{id}/challenge/`
  - `POST /api/csa/answers/{id}/resolve/`
  - `?weak=true` filter on responses surfaces just the flagged ones
- **Audit-log integration** — every domain action (submit, challenge, resolve, close) records an `AuditLogEntry` with the structured event payload.
- **23 new tests** in `iams/tests/test_csa.py` covering scoring math (yes/no, scale 1-5, evidence-required), per-category split, weak-control notification + entity risk bump (with Critical preservation), full challenge workflow (open → resolve → close), and RBAC gating.

### Test totals
- **Backend: 421 passing** (was 398; added 23).

## [0.10.0] — Phase 3 Track 2: QAIP (2026-05-12)

### Added
- **Four QAIP models** ([migration 0013](iams/migrations/0013_auditkpi_qaipassessment_qaipfinding_and_more.py)) — FR-QAIP-01..06:
  - `QAIPAssessment` — internal / external / peer / post-engagement review of the IA function. Status + overall rating + lead reviewer FK + scope/methodology/summary.
  - `QAIPFinding` — *distinct* from regular `Finding`; raised against the audit function itself. Severity (critical/high/medium/low), owner (text + optional FK), recommendation, due date.
  - `StakeholderSurvey` — satisfaction (1-5) with **DB-level check constraint**, optional audit FK, role taxonomy, **anonymous** flag (scrubs the respondent FK on save AND defensively on serialise).
  - `AuditKPI` — kpi_type × period (unique constraint), target vs actual, direction (higher_is_better / lower_is_better), computed `variance` + `favorable` on read.
- **Serializers** with camelCase + computed counts (`findingsCount`, `openFindingsCount` from prefetch cache to avoid N+1) + computed `variance` / `favorable`.
- **Four QAIP ViewSets** at `/api/qaip/{assessments,findings,surveys,kpis}/` — gated by `view_reports` (read+write, matching `AuditReportViewSet` precedent). All run through `AuditedViewSetMixin` so every state change writes an `AuditLogEntry`.
- **`/api/qaip/dashboard/`** aggregate endpoint — assessments-by-type/status, open + critical QAIP findings, avg satisfaction across surveys, latest-period KPI rollup. Supports `?period=` filter.
- **18 QAIP tests** in `iams/tests/test_qaip.py` — CRUD, filters, computed counts, anonymity scrubbing on save + on serialise, DB check constraint on score range, KPI variance + favorable in both directions, uniqueness constraint, dashboard math, RBAC gating.

### Notes
- QAIP findings deliberately do **not** share a model with audit `Finding`. The two have different owners (IA team vs auditees), different lifecycles, and different reporting flows.
- Annual QAIP Report PDF generation (FR-QAIP-04 export to PDF) is deferred to Phase 4 Track 2 where WeasyPrint integration lands.
- **Backend tests: 398 passing** (was 380; added 18).

## [0.9.0] — Phase 3 Track 1: Working Papers + sign-off + versioning (2026-05-12)

### Added
- **`WorkingPaper` model** ([migration 0012](iams/migrations/0012_workingpaper.py)) — engagement-scoped audit working papers. Includes:
  - Reference + title + description + file + file_type + file_size_kb
  - Status (Draft / Under Review / Signed / Archived)
  - Version chain: `parent` self-FK, `version` integer, `is_current_version` boolean (partial unique constraint enforces one current row per (audit, reference))
  - Multi-step sign-off: `auditor_signed_by/at`, `reviewer_signed_by/at`, derived `signed_off_at`
  - Cross-references to `Finding` via M2M (FR-WP-04)
  - AV scan state mirroring `EvidenceFile` (`scan_status`, `scan_signature`, `scanned_at`, `quarantined`)
  - `searchable_text` for case-insensitive contains queries (works on Postgres + SQLite)
- **Python-level lock-on-finalize** (FR-WP-06) — `WorkingPaper.save()` rejects updates to a row with `signed_off_at` set; `delete()` raises `PermissionError`. AV scan-only updates (`scan_status`/`scan_signature`/`scanned_at`/`quarantined`) are explicitly allowed so the worker can still write its verdict after sign-off.
- **`iams/working_papers.py` service module**:
  - `sign_as_auditor(wp, by_user)` — records auditor signature; rejects double-sign.
  - `sign_as_reviewer(wp, by_user)` — records reviewer signature, sets `signed_off_at`, locks. Enforces **IIA 2330 separation of duties** (reviewer ≠ auditor).
  - `create_new_version(parent, file=, title=, description=)` — atomic: flips parent's `is_current_version` to False, inserts new row with cleared signatures + reset scan state, copies cross-references forward.
  - `populate_searchable_text(wp)` — stub extractor (real `unstructured`/`pdfplumber` integration is a follow-up).
- **`WorkingPaperViewSet`** at `/api/working-papers/`:
  - List filterable by `?audit_id=` / `?currentOnly=true` / `?status=` / `?search=`
  - `POST /` — multipart create (computes `file_size_kb`, populates `searchable_text`, dispatches AV scan)
  - `PATCH /{id}/` — rejected with **403** once signed off
  - `POST /{id}/sign/auditor/` + `/sign/reviewer/` — atomic sign-off + audit-log event
  - `POST /{id}/new-version/` — multipart; auto-flips parent's `is_current_version`
  - `GET /{id}/versions/` — full chain in order 1→N
  - `GET /{id}/download/` — signed URL; 403 on quarantine, 409 while scan pending
- **AV scan task** now recognises `model_label="WorkingPaper"` (added to `_SCANNABLE_MODELS`).
- **Audit-log events** — sign-off and new-version actions both record `AuditLogEntry` rows with the event payload (auditor_signed / reviewer_signed / new_version with parent_id + version).
- **22 working-paper tests** in `iams/tests/test_working_papers.py`.

### Notes
- Real document text extraction (PDF/Word) is deferred — the stub indexes title + description + reference + plain-text content for now. Phase 3 Track 1.1 will integrate `unstructured` (already on the dependency wishlist) + a Celery task.
- The `(audit, reference, is_current_version=True)` partial unique constraint runs on Postgres; SQLite test runs validate the Python-level guard.
- **Backend tests: 380 passing** (was 358; added 22).

## [0.8.0] — Phase 2 Track 3: Approval workflow engine + escalation (2026-05-12)

### Added
- **`ApprovalChainTemplate` model** — configurable, per-`request_type` approval chain. JSON `chain` field of `{role, sla_days}` step descriptors. DB-level unique-active constraint per request type (`iams_one_active_chain_per_type`).
- **`ApprovalStep` SLA fields** (migration 0011): `sla_days`, `due_at` (db_index), `escalated_at`.
- **`ApprovalRequest.last_action_at`** for telemetry and FE staleness badges.
- **Workflow service module** `iams/workflows.py`:
  - `apply_chain_template(request)` — expands the active template into `ApprovalStep` rows; idempotent.
  - `can_user_action(request, user)` — authorisation: approver email match, OR role match, OR super-admin bypass.
  - `advance_on_approve(request, by_user, comment)` — locked to designated approver. Advances `current_step`, promotes the next step's `due_at`, and fires the `approval_request_approved` signal when the chain completes.
  - `reject_request(request, by_user, comment)` — short-circuits + fires `approval_request_rejected`.
  - `overdue_pending_steps()` — read-only generator for the escalation task.
- **Domain signals** `approval_request_approved`, `approval_request_rejected`, `approval_step_escalated` — emitted by the workflow engine for downstream consumers.
- **Auto-apply chain on creation** — `post_save` signal expands the active `ApprovalChainTemplate` into steps whenever an `ApprovalRequest` is created without inline steps.
- **Domain-specific side-effect handlers** (in `iams/signals.py`):
  - `CAP Closure` approved → marks the CAP `Closed` + `progress=100`.
  - `Report` approved → marks the `AuditReport` `Final`.
  - `Audit Plan` approved → logs the gating transition (downstream behavior in Phase 4).
- **Escalation Celery task** `iams.workflows.escalate_overdue_steps`:
  - Stamps `escalated_at` on overdue pending steps (24h dedupe).
  - Re-pings the original approver with escalated wording.
  - Broadcasts a heads-up to every active Audit Manager via `dispatch_to_role`.
  - Records `approval_step_escalated` audit-log event (actor `system:escalation`).
  - Sends the `approval_step_escalated` signal for future consumers.
- **Beat schedule** — nightly at 03:00 local.
- **`ApprovalChainTemplateViewSet`** at `/api/approval-chain-templates/`. Reads gated by `view_audits`; writes by `manage_settings`.
- **`?mine=pending`** filter on `/api/approval-requests/` — returns requests whose current pending step matches the caller's email OR role.
- **`seed_approval_chains` management command** — seeds 5 default templates (Audit Plan, CAP Closure, Finding, Report, Risk Assessment). Idempotent; `--activate` to force-activate after seed.

### Changed
- `ApprovalRequestViewSet.approve` / `.reject` now route through the workflow service. **Unauthorised approvers get 400 with a clear "not the designated approver" message.** Audit-log events now capture the step role + final request status.
- `ApprovalStepSerializer` exposes `slaDays`, `dueAt`, `escalatedAt`, `overdue` (computed: pending AND past due_at). `ApprovalRequestSerializer` exposes `lastActionAt`.

### Test totals
- **Backend: 358 passing** (was 339; added 19 workflow tests). Coverage stable.
- Updated legacy test to satisfy the new approver-lockdown rule.

### Notes
- The Postgres `Q(escalated_at__isnull=True) | Q(escalated_at__lt=cutoff)` dedupe is checked **before** `escalated_at` is stamped in the task, so re-running mid-window is a true no-op (verified by `test_escalation_is_deduped_per_24h`).

## [0.7.0] — Phase 2 Track 2: Notifications + email pipeline (2026-05-12)

### Added
- **14-kind notification taxonomy** on `Notification.KIND_*` — `audit_assigned`, `audit_status_change`, `finding_raised`, `cap_assigned`, `cap_due_soon`, `cap_overdue`, `approval_requested`, `approval_approved`, `approval_rejected`, `password_reset`, `file_quarantine`, `weekly_digest`, `mfa_reminder`, `generic`.
- **Notification model extended** (migration 0010): `recipient` FK (NULL = system broadcast), `kind`, `target_content_type`/`target_object_id` GenericFK, `link`, `module`, `email_sent_at`, indexes on `(recipient, read, -timestamp)` + `(kind, -timestamp)`.
- **`NotificationPreference` model** — per-user × per-kind toggles for in-app and email. Unique constraint on `(user, kind)`. Defaults supplied server-side so the FE matrix is always complete on first render.
- **`iams.notifications.dispatch(...)`** — single chokepoint for every notification event. Resolves user prefs (with `DEFAULT_PREFS` fallback), writes in-app row, enqueues email task. Never raises into caller.
- **`iams.notifications.dispatch_to_role(role_name, ...)`** — fan-out helper for escalation flows.
- **`iams.tasks.notify.deliver_email`** Celery task — autoretrying, marks the originating `Notification.email_sent_at`.
- **Scheduled tasks** (`CELERY_BEAT_SCHEDULE`):
  - `iams.notify.cap_overdue_scan` — nightly at 02:00 local. Notifies CAP owners about overdue + due-in-3-days CAPs. Deduped to once-per-24h per CAP.
  - `iams.notify.weekly_digest` — Mondays at 08:00 local. Each active user gets a personalised digest (open / overdue CAPs) plus org-wide stats.
- **Email templates** at `iams/templates/iams/email/notification.{txt,html}` — responsive HTML + plain-text.
- **Signal handlers** (`iams/signals.py` connected via `IamsConfig.ready()`):
  - `CorrectiveAction.post_save` → notify owner on create
  - `Finding.post_save` → notify owner + audit lead on create (severity-aware level)
  - `AuditAssignment.post_save` → notify auditor on create
  - `ApprovalRequest.post_save` → notify submitter on approved/rejected transition
  - `ApprovalStep.post_save` → notify approver when their pending step is created
- **API endpoints**:
  - `GET /api/notifications/` is now **per-user scoped** (includes `recipient=NULL` broadcasts).
  - `GET /api/notifications/unread-count/` — tiny endpoint the FE bell polls every 60s.
  - `GET /api/notification-preferences/` — merged defaults + stored rows, one entry per kind.
  - `POST /api/notification-preferences/` — upsert by `kind`.
- **Existing `mark-read` / `mark-all-read`** actions now honor user scoping.
- **22 new notification tests** in `iams/tests/test_notifications.py` (dispatcher pref-gating, signal-driven flows, beat tasks with dedupe, API scoping, preference upsert, role broadcast).

### Configuration
- `CELERY_BEAT_SCHEDULE` declared in `config/settings/base.py` — DatabaseScheduler still wins, but these are the defaults installed on first start.

### Test totals
- **Backend: 339 passing** (was 317; added 22 notification tests). Coverage stable.

## [0.6.0] — Phase 2 Track 1: Automatic audit trail (2026-05-12)

### Added
- **`AuditedViewSetMixin`** in [iams/audit.py](iams/audit.py) — drop-in mixin for any `ModelViewSet` that captures every create/update/delete and writes an `AuditLogEntry` row with:
  - actor (display + FK), action verb, target (str + GenericFK)
  - `request_id` from middleware, IP (X-Forwarded-For aware), truncated user-agent
  - `changes` payload: `{field: {old, new}}` diff on update, `{snapshot: {...}}` on create/delete
  - Idempotent PATCH (no actual changes) does not write a row
  - Failed audit capture never breaks the user request — exception is logged and swallowed
- **`record_audit_event(...)` helper** for non-CRUD events: login, approval, password change/reset, file_quarantine, export.
- **AuditLogEntry model fields** (migration 0008): `request_id`, `ip_address`, `user_agent`, `changes` (JSON). Plus DB indexes for `-timestamp`, `(actor_ref, -timestamp)`, `(target_content_type, target_object_id)`, `(action, -timestamp)`.
- **Action verb constants** on `AuditLogEntry` — `ACTION_CREATE`, `ACTION_UPDATE`, `ACTION_DELETE`, `ACTION_APPROVE`, `ACTION_REJECT`, `ACTION_LOGIN`, `ACTION_LOGOUT`, `ACTION_PASSWORD_RESET`, `ACTION_PASSWORD_CHANGE`, `ACTION_FILE_UPLOAD`, `ACTION_FILE_QUARANTINE`, `ACTION_EXPORT`, `ACTION_OTHER`.
- **Python append-only enforcement** — `AuditLogEntry.save()` rejects updates after first INSERT (via `_state.adding`); `delete()` raises `PermissionError`.
- **DB-level append-only enforcement** (migration 0009) — Postgres `BEFORE UPDATE OR DELETE` trigger raises `iams_auditlogentry is append-only`. SQLite (test) skips the trigger; Python guard remains.
- **Privileged retention escape** — trigger respects `current_setting('iams.allow_audit_log_modification')` so the Phase 5 retention worker can purge expired rows under controlled session.
- **13 new audit-trail tests** in [iams/tests/test_audit_trail.py](iams/tests/test_audit_trail.py).

### Behavior
- Every write-able ViewSet now auto-captures:
  `AuditViewSet`, `FindingViewSet`, `CorrectiveActionViewSet`, `ChecklistItemViewSet`, `FollowUpViewSet`, `CommentViewSet`, `AuditorViewSet`, `AssignmentViewSet`, `TimeEntryViewSet`, `HoursBudgetViewSet`, `RiskAssessmentViewSet`, `ApprovalRequestViewSet`, `WorkProgramViewSet`, `WorkProcedureViewSet`, `WorkProcedureStepViewSet`, `AuditReportViewSet`, `AuditReportSectionViewSet`, `ManagedDocumentViewSet`, `UserViewSet`.
- **`ApprovalRequestViewSet.approve` / `.reject`** now record explicit `approve`/`reject` events with step role + comments in `details`.
- **`PasswordChangeView`** records `password_change`.
- **`PasswordResetConfirmView`** records `password_reset` with `via=reset_token`.
- **AV scan task** records `file_quarantine` (actor `system:clamav`) when a file is flagged.
- **User passwords** are in the global excluded-fields set — never appear in the audit log.

### Serializer
- `AuditLogEntrySerializer` now exposes: `requestId`, `ipAddress`, `userAgent`, `targetType`, `targetId`, `changes`, plus the existing `actor`/`action`/`target`/`timestamp`/`details`.

### Test totals
- **Backend: 317 passing** (was 304; added 13 audit-trail tests). Coverage stable.

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
