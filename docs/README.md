# IAMS — Internal Audit Management System

An enterprise-grade internal audit platform built on **Django REST Framework** + **React/Vite/TypeScript**, designed for on-premise deployment with full integration into corporate Active Directory, ERP / HRIS systems, and a self-hosted observability stack.

| Component | Stack | Where |
|---|---|---|
| Backend API | Django 6 · DRF · SimpleJWT · Celery · PostgreSQL 16 · Redis 7 · MinIO · ClamAV | this repo (`iams-backend`) |
| Frontend SPA | React 18 · Vite · TypeScript strict · Tailwind · shadcn/ui · react-i18next | separate repo (`iams-frontend`) |
| Deploy assets | docker-compose · nginx · Prometheus · Grafana · Loki · Tempo | [`deploy/`](../deploy/) + [`docker-compose.prod.yml`](../docker-compose.prod.yml) |
| CI/CD | GitHub Actions · Trivy · blue-green deploy | `.github/workflows/` in each repo |

---

## Quick links

- **[Admin guide](admin-guide.md)** — for operators / IT admins: install, configure, integrate, monitor.
- **[User guide](user-guide.md)** — for end users by role: auditor, manager, auditee, executive.
- **[API reference](api-reference.md)** — narrative API docs + how to use the auto-generated OpenAPI schema.
- **[Training scripts](training-scripts/)** — text-based scripts for the 5 video walkthroughs (intro + role-specific + admin).
- **[Migration checklist](MIGRATION-CHECKLIST.md)** — the N-1 rule and safe-migration patterns. Required reading before any schema PR.
- **[Implementation plan](IMPLEMENTATION-PLAN.md)** — the original 6-phase plan with FR / NFR cross-refs.
- **[Database design](DATABASE_DESIGN.md)** — entity relationships and partial-unique constraints.
- **[Requirements](IAMS-Requirements-Document.md)** — the canonical FR-* + NFR-* list.

## Phase reports

| Phase | Title | Highlights |
|---|---|---|
| 0 | Foundations | Settings split, observability primitives, CI, JWT auth, RBAC |
| 1 | Core domain | Audit, Finding, CAP, Approval, Working Papers |
| 2 | Workflow + Notifications | Email + in-app, approval chains, escalation |
| 3 | Quality + Compliance | QAIP, CSA, ICFR |
| 4 | Risk + Reports + Dashboards | Risk engine, PDF/Excel renderers, role bundles |
| **5** | **Enterprise hardening** | **MFA, perf indexes, Prometheus + Grafana, CI/CD blue-green** |
| **6** | **Integrations + polish** | **Keycloak SSO, ERP/HR webhooks, i18n + a11y, docs** |

Per-track close-outs live in this folder (e.g. `phase-5-track-3-report.md`). Phase-level summaries: [Phase 4](phase-4-closeout-report.md), [Phase 5](phase-5-closeout-report.md).

## At a glance

- **637 backend tests passing**, strict TypeScript across the FE.
- **22 migrations**, all backward-compatible per the [N-1 rule](MIGRATION-CHECKLIST.md).
- **Three locales** — English, Arabic (RTL), French.
- **MFA (TOTP)** in-app + **Keycloak / OIDC SSO** with AD federation.
- **OpenAPI 3.1** schema + auto-generated FE typed clients.
- **Blue-green deploy** with migration-before-flip safety net.
- **Prometheus + Grafana** dashboards for system + business metrics, **OTel** traces.
- **`pg_dump` → `age` → `restic`** backup pipeline with quarterly drill.

## Running locally

```bash
# Backend
cd iams-backend
uv sync
uv run python manage.py migrate
uv run python manage.py runserver

# Frontend (separate terminal)
cd iams-frontend
npm install
npm run dev
```

The backend defaults to SQLite for dev; production deployments use PostgreSQL via `DATABASE_URL`. See the [admin guide](admin-guide.md) for the full environment variable matrix.

## Running tests

```bash
# Backend
cd iams-backend
IAMS_DISABLE_PDF_RENDER=1 uv run pytest

# Frontend
cd iams-frontend
npx tsc --noEmit         # strict typecheck
npx vitest run           # unit tests
npm run build            # production bundle
```

## Project status

Phase 6 closed out **2026-05-13**. Production-shippable. Ongoing work is operational (monitoring, retros, feature requests) rather than greenfield.

---

🤖 Generated with [Claude Code](https://claude.com/claude-code)
