# Phase 6 — Close-Out Report

**Date:** 2026-05-13
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 6
**Status:** ✅ Complete

Phase 6 ("Integrations & Polish") takes IAMS from a hardened-but-island product to a system that lives inside a real enterprise. SSO bridges to corporate AD; ERP/HR webhooks land canonical data; the UI works in three locales with RTL Arabic; the documentation set is shipped with the code.

---

## Tracks shipped

| # | Title | Version | Tests added |
|---|---|---|---:|
| 1 | Keycloak / OIDC SSO | `0.20.0` | +20 |
| 2 | ERP / HR Integrations | `0.21.0` | +25 |
| 3 | Accessibility & i18n | `0.22.0` | +6 (BE) + 9 (FE) |
| 4 | Documentation & Training | `0.23.0` | 0 |
| **Phase 6 total** | | | **+51 BE, +9 FE** |

Test suite: **586 → 637** backend tests passing; 9 FE i18n tests passing under vitest.

---

## What this means for the product

### For corporate identity
- **Sign in with Active Directory.** Keycloak federates AD via LDAP; first-time SSO users JIT-provision into IAMS with a default role.
- **Group → role mapping.** Operator wires Keycloak groups (`/IAMS/Auditors`, `/IAMS/Managers`) to IAMS roles. Precedence-ordered when a user is in multiple groups.
- **Password login still works.** Service accounts and break-glass aren't blocked by SSO config.

### For data flow
- **Inbound webhooks** for `auditable_entity` + `finding` from SAP / Oracle / Odoo. HMAC-SHA256 signed. Idempotent upsert by `(external_source, external_id)`. Every delivery — accepted or rejected — lands in an audit-grade event ledger.
- **Outbound user push** to AD / HRIS targets. Every `User.save()` fans out to active outbound-enabled sources. Failures are rowed for retry.
- **The event ledger** at `/api/integrations/events/` is the operator's source of truth for integration health.

### For accessibility & internationalization
- **Three locales** — English, Arabic (RTL), French. Per-user preference persists on `UserProfile.language` and syncs across devices.
- **WCAG 2.1 AA primitives** — skip-to-content link, aria-live regions, accessible language switcher. Eager direction flip means `document.documentElement.dir/lang` is always correct synchronously.
- **A11y namespace** in every locale bundle. Tests assert keys exist in all three.

### For long-term operability
- **README** at repo root with quick-start commands and links to every doc.
- **Admin guide** — full env-var matrix, deployment runbook, SSO + integration wiring, backup procedures, troubleshooting.
- **User guide** — by-role how-to for the four primary personas.
- **API reference** — narrative companion to the OpenAPI schema; covers conventions, the `code` error taxonomy, rate limits, typed-client generation.
- **Training scripts** for 5 walkthrough videos (intro + 4 role-specific).

---

## Architectural decisions worth recording

1. **Mint our own JWT after OIDC code exchange.** Downstream API path stays identical to password auth. The OIDC trust boundary terminates at the callback view.
2. **Mutual HMAC on outbound integration pushes.** Both bearer (RFC 6750) and `X-IAMS-Signature` body hash. Receivers can verify origin even when TLS terminates at a proxy.
3. **Reject *and* record.** Inbound validation runs outside `transaction.atomic()` so rejection events persist even on raised exceptions. Operator sees every malformed delivery in the ledger.
4. **Server-side gettext deferred.** Every backend error carries a stable `code`; the FE translates. Adding a locale doesn't require a backend deploy.
5. **Cardinality-disciplined metrics.** Phase 5 set the rule; Phase 6 follows: no per-id labels in Prometheus.
6. **Documentation in `docs/`, README at root.** Standard discoverability. Phase-track reports keep their place as the design *why*; the new guides are the *how*.

---

## Six-phase project total

| Phase | Title | Versions | Tests |
|---|---|---|---:|
| 0 | Foundations | 0.1.x – 0.2.x | 5 |
| 1 | Core domain | 0.3.x – 0.6.x | 32 → 290 |
| 2 | Workflow + Notifications | 0.7.x – 0.9.x | 290 → 353 |
| 3 | Quality + Compliance | 0.10.x – 0.12.x | 353 → 417 |
| 4 | Risk + Reports + Dashboards | 0.13.x – 0.15.x | 417 → 540 |
| 5 | Enterprise hardening | 0.16.x – 0.19.x | 540 → 586 |
| 6 | Integrations + polish | 0.20.x – 0.23.x | 586 → **637** |

- **22 migrations**, all backward-compatible per the [N-1 rule](../MIGRATION-CHECKLIST.md).
- **Strict TypeScript** across the FE — every typed client clean.
- **Production-shippable**: blue-green deploy, backups + restore drill, observability end-to-end, SSO + MFA, three locales, full documentation set.

---

## Operator readiness

- **All migrations applied locally.** No pending model changes.
- **All 637 BE tests green** with `IAMS_DISABLE_PDF_RENDER=1`.
- **All FE tests green** under vitest; `tsc --noEmit` clean.
- **CI/CD pipeline in place**: PRs run lint/typecheck/test/build/contract. Main pushes auto-deploy to staging + smoke-test. Tags promote to production behind a manual gate.
- **Backup pipeline tested**. Restore script ready for the quarterly drill.
- **Monitoring assets checked in**. Grafana dashboards + Prometheus alert rules in `deploy/`.

The user asked for "everything — leave nothing optional, enterprise grade, production ready." Phase 6 closes that out.
