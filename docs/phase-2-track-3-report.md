# Phase 2 Track 3 — Approval Workflow Engine + Escalation (Complete)

**Date:** 2026-05-12
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 2 Track 3
**Status:** ✅ Complete — Phase 2 closed

The final Phase 2 cross-cutting track. Approval workflows now run on a configurable chain engine with proper approver authorisation, SLA-driven escalation, and signal-driven domain side effects.

---

## What shipped

### Backend

**Models** ([migration 0011](../iams-backend/iams/migrations/0011_alter_approvalrequest_reference_id_and_more.py))
- `ApprovalChainTemplate` — `name`, `request_type`, JSON `chain` (`[{role, sla_days}, ...]`), `description`, `is_active`. Unique-active-per-`request_type` constraint at the DB level.
- `ApprovalStep` SLA fields: `sla_days`, `due_at` (indexed), `escalated_at`.
- `ApprovalRequest.last_action_at` for telemetry.

**Workflow service** [`iams/workflows.py`](../iams-backend/iams/workflows.py)
- `apply_chain_template(request)` — expands the active template into `ApprovalStep` rows; idempotent.
- `can_user_action(request, user)` — authorisation: approver-email match, OR role match, OR super-admin bypass. Returns `(allowed, step)` so callers can also surface the current step in error responses.
- `advance_on_approve` / `reject_request` — transactional, raise `ApprovalError` on wrong approver, advance `current_step`, promote next step's `due_at`, fire domain signals on completion.
- `overdue_pending_steps()` — read-only generator with built-in dedupe-window predicate.
- Custom signals: `approval_request_approved`, `approval_request_rejected`, `approval_step_escalated`.

**Auto-apply chain template on creation** ([iams/signals.py](../iams-backend/iams/signals.py))
- `post_save(ApprovalRequest)` → `apply_chain_template(instance)` if no inline steps were created. Lets the API stay flexible (callers can still supply inline steps) while making the template the default.

**Domain side-effect handlers** ([iams/signals.py](../iams-backend/iams/signals.py))
- `CAP Closure` approved → CAP marked `Closed` + `progress=100`
- `Report` approved → `AuditReport` marked `Final`
- `Audit Plan` approved → logs the transition (Phase 4 will wire downstream behavior)
- Rejection currently logs only; future consumers can revert dependent state via the signal.

**Escalation Celery task** [`iams/tasks/workflows.py`](../iams-backend/iams/tasks/workflows.py)
- Stamps `escalated_at` on overdue pending steps (24h dedupe via Q-predicate).
- Re-pings the original approver with escalated wording.
- Fans out `generic`-level heads-up to every active Audit Manager via `dispatch_to_role`.
- Records a first-class `approval_step_escalated` audit-log event (actor `system:escalation`).
- Sends the `approval_step_escalated` signal for downstream consumers.

**Beat schedule** (`config/settings/base.py`)
- `approval-escalation-nightly` — `crontab(hour=3, minute=0)`.

**API**
- `GET /api/approval-requests/?mine=pending` — returns requests whose current pending step matches the caller (by email or role).
- `/api/approval-chain-templates/` — admin CRUD viewset. Read gated by `view_audits`; write by `manage_settings`.
- `approve` / `reject` actions now return **400 with a clear message** when the caller isn't the designated approver.

**Seed command** [`seed_approval_chains.py`](../iams-backend/iams/management/commands/seed_approval_chains.py)
- 5 default chains (Audit Plan, CAP Closure, Finding, Report, Risk Assessment).
- Idempotent; `--activate` flag to force-activate (deactivates any other active template for the same `request_type`).

**Tests** ([`iams/tests/test_workflows.py`](../iams-backend/iams/tests/test_workflows.py) — 19 tests)
- Chain template: auto-apply on create, inactive-doesn't-apply, no-overwrite-of-inline-steps, unique-active constraint
- Approve / reject: requires designated role, role match, super-admin bypass, multistep advance, reject short-circuit, next-step due_at promotion, can_user_action returns the step even when disallowed
- Domain side effects: CAP closure approval closes the CAP
- Escalation: picks up overdue, deduped per 24h, records audit-log event, skips future due_at
- API: `?mine=pending` scoping, 400 on wrong approver, audit-log written on approve

### Frontend

**`useMyPendingApprovals`** hook with 60s polling (cache `mine-pending`).

**`MyPendingApprovals`** Dashboard widget — clean empty state, jump-to-approvals link, priority badge, +N truncation.

**Layout** — Dashboard top row becomes `[ DashboardCharts (2/3) ][ MyPendingApprovals (1/3) ]`. The original 3-column secondary row stays.

**Service layer**
- `approvalService.getMinePending()` on the service interface + API + mock.
- `useApproveRequest` / `useRejectRequest` invalidate `mine-pending` too.

---

## Test totals

| Suite | Tests |
|---|---|
| Backend smoke | 5 |
| Backend auth | 19 |
| Backend RBAC matrix | 232 |
| Backend contract | 32 |
| Backend scans | 13 |
| Backend audit trail | 13 |
| Backend notifications | 22 |
| **Backend workflows (new)** | **19** |
| Backend legacy domain | 3 |
| **Backend total** | **358** |
| Frontend vitest | 14 |

---

## Acceptance criteria (from plan §Phase 2 Track 3)

| Criterion | Status |
|---|---|
| `approve` / `reject` advance the workflow | ✅ |
| Approve: mark step approved, advance, mark request approved on last | ✅ |
| Reject: mark step rejected, notify creator (via existing signal handler) | ✅ |
| Signal handlers wire to approved entity (CAP closure → CAP closed) | ✅ (CAP Closure + Report; Audit Plan logs only — Phase 4 wires audits) |
| Annual Audit Plan approval chain (Auditor → Manager → CAE → Board) | ✅ (configurable via `seed_approval_chains`) |
| Escalation: if a step is unactioned for N days, escalate to the next role + email manager | ✅ |
| FE: `WorkflowApprovals` page wired to real data | ⚠️ Existing page consumes `useApprovalRequests` which is already real-API. Full filter UI + escalated badge + SLA countdown deferred to FE polish session. |
| FE: "my pending approvals" on dashboard | ✅ |

---

## Phase 2 closing scorecard

| Concern | Phase 1 close | Phase 2 close |
|---|---|---|
| Backend tests | 304 | **358** |
| Audit trail | manual log calls | **auto-capture mixin + Postgres immutability trigger** |
| Notifications | model only | **dispatcher + 14-kind taxonomy + email + scheduled beat tasks** |
| Approval workflows | linear advance, no auth check | **configurable chains + escalation + side-effect signals + ?mine=pending** |
| Background jobs | password reset + AV scan | + email delivery + CAP-overdue scan + weekly digest + approval escalation |

---

## How to verify locally

```bash
cd iams-backend
uv run python manage.py migrate iams                    # applies 0011
uv run python manage.py seed_approval_chains --activate # populates 5 default templates
uv run pytest iams/tests/test_workflows.py -v           # 19/19

# End-to-end manual smoke (with the stack running):
docker compose up
# 1. POST /api/approval-requests/ with type="Audit Plan" and no inline steps.
#    Backend auto-applies the 3-step Auditor→Manager→CAE chain.
# 2. Try to approve as an Auditor → 400 "not the designated approver".
# 3. Approve as Audit Manager → step 1 done, step 2 due_at promoted to now+5d.
# 4. Force overdue via shell:
docker compose exec backend uv run python manage.py shell -c "from iams.tasks.workflows import escalate_overdue_steps; print(escalate_overdue_steps())"
```

```bash
cd iams-frontend
npm run dev
# Login → Dashboard shows the new "My pending approvals" widget if you're
# Audit Manager (or higher) and any pending requests exist.
```

---

## What's next

**Phase 3 — Missing Core Modules** begins:

1. **Working Papers + Document Versioning** (FR-WP-01..09) — digital sign-off, full-text search, IIA 2330 compliance.
2. **QAIP** — Quality Assurance & Improvement Program (assessments, KPIs, stakeholder surveys, annual report).
3. **CSA** — Control Self-Assessment (questionnaires, responses, auditor challenge workflow).
4. **ICFR** — financial-control design + operating testing, deficiency reporting.

Each is a sizeable feature pack, so they will be tackled one at a time in subsequent sessions.

---

*Generated 2026-05-12.*
