# Phase 2 Track 1 — Automatic Audit Trail (Complete)

**Date:** 2026-05-12
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 2 Track 1
**Status:** ✅ Complete

The first of three Phase 2 cross-cutting tracks. The system **audits audits** — its own log integrity is the product. This track guarantees that every meaningful state change writes an immutable, queryable, request-correlated row to `AuditLogEntry`, without any per-viewset code.

---

## What shipped

### Backend (`iams-backend`)

**`iams/audit.py` — the central capture module**
- `AuditedViewSetMixin` — drop-in mixin for any DRF `ModelViewSet`. Captures `perform_create` / `perform_update` / `perform_destroy` automatically:
  - **Update** entries carry a `{field: {old, new}}` diff of *only the changed fields*. Idempotent PATCH = no row.
  - **Create / delete** entries carry a `{"snapshot": {...}}` of the row at the moment of action.
  - Excluded fields (passwords, `created_at`, `updated_at`, FileField bytes) never appear.
  - Failed audit capture is logged and swallowed — user actions never break because the audit failed.
- `record_audit_event(...)` helper for non-CRUD events (approve, reject, password reset/change, file quarantine, login).
- Both produce rows with: actor (display + FK), action verb, target (str + GenericFK), `request_id`, IP (X-Forwarded-For aware), user-agent.

**Model — `AuditLogEntry` (migration 0008)**
- New fields: `request_id`, `ip_address`, `user_agent`, `changes` (JSON).
- New DB indexes: `(-timestamp)`, `(actor_ref, -timestamp)`, `(target_content_type, target_object_id)`, `(action, -timestamp)`.
- 14 action verb constants on the class — the canonical taxonomy.

**Python-level immutability**
- `AuditLogEntry.save()` rejects any save where `_state.adding=False` — instances loaded from DB cannot be re-saved.
- `AuditLogEntry.delete()` raises `PermissionError`.

**DB-level immutability** (migration 0009)
- Postgres `BEFORE UPDATE OR DELETE` trigger that raises `iams_auditlogentry is append-only`.
- Privileged retention escape: the trigger respects `current_setting('iams.allow_audit_log_modification')`, so the Phase 5 retention worker can purge expired partitions under a controlled session.
- SQLite (test environment) skips the trigger; Python guard remains the only enforcement.

**Mixin applied to every write-able ViewSet** (19 of them):
`AuditViewSet`, `FindingViewSet`, `CorrectiveActionViewSet`, `ChecklistItemViewSet`, `FollowUpViewSet`, `CommentViewSet`, `AuditorViewSet`, `AssignmentViewSet`, `TimeEntryViewSet`, `HoursBudgetViewSet`, `RiskAssessmentViewSet`, `ApprovalRequestViewSet`, `WorkProgramViewSet`, `WorkProcedureViewSet`, `WorkProcedureStepViewSet`, `AuditReportViewSet`, `AuditReportSectionViewSet`, `ManagedDocumentViewSet`, `UserViewSet`.

**Explicit hooks**
- `ApprovalRequestViewSet.approve` / `.reject` → records `approve`/`reject` with step + comments.
- `PasswordChangeView` → `password_change`.
- `PasswordResetConfirmView` → `password_reset` with `via=reset_token`.
- `scan_uploaded_file` Celery task → `file_quarantine` (actor `system:clamav`) on virus detection.

**Serializer**
`AuditLogEntrySerializer` now exposes: `requestId`, `ipAddress`, `userAgent`, `targetType`, `targetId`, `changes`, plus the original `actor`/`action`/`target`/`timestamp`/`details`.

### Frontend (`iams-frontend`)

**`src/components/AuditChangesViewer.tsx`**
- Renders both shapes the backend emits:
  - **Diff** (`{field: {old, new}}`): two-column old→new with destructive/success pills and an arrow icon.
  - **Snapshot** (`{snapshot: {...}}`): flat key/value list for create/delete events.
- Returns `null` for empty `changes` so callers don't need to guard.

**`src/pages/AuditLog.tsx`**
- Detail Sheet now renders `AuditChangesViewer` + `requestId` block.
- Filter dropdown extended to the full 14-action taxonomy.
- All `actionLabel`/`actionBadge`/`actionIcon` lookups go through bounds-safe `labelFor`/`badgeFor`/`iconFor` helpers — no `string | undefined` strict-mode errors when a new verb arrives.

**`src/data/mock-data.ts`**
- `AuditLogAction` enum extracted, expanded to cover backend's full set.
- `AuditLogEntry` interface gains optional `actor`, `targetType`, `targetId`, `requestId`, `userAgent`, `changes` fields. Existing FE-mock fields (`user`, `module`, free-text `details`) stay for backward compatibility — a focused FE cleanup will collapse them in a later session.

---

## Test totals

| Suite | Tests |
|---|---|
| Backend smoke | 5 |
| Backend auth | 19 |
| Backend RBAC matrix | 232 |
| Backend contract | 32 |
| Backend scans | 13 |
| **Backend audit trail (new)** | **13** |
| Backend legacy domain | 3 |
| **Backend total** | **317** |
| Frontend vitest | 14 |

---

## Acceptance criteria (from plan §Phase 2 Track 1)

| Criterion | Status |
|---|---|
| Every state change produces an immutable, queryable, request-ID-correlated log entry | ✅ |
| Diff payload: `{field: {old, new}}` | ✅ |
| GenericForeignKey to changed object | ✅ |
| Actor from `request.user`, request_id from middleware | ✅ |
| Immutability via Postgres trigger (with privileged-retention escape) | ✅ |
| Immutability via Python `save()` / `delete()` overrides | ✅ |
| FE: filters + structured diff viewer | ✅ |
| 7-year retention via scheduled Celery task | ⏳ Phase 2 Track 2 (notifications track) sets up the Celery beat schedule; the retention task itself is Phase 5 hardening |
| Tests covering signal flows (freezegun) | ✅ (request metadata + helper + viewset path) |

---

## How to verify locally

```bash
cd iams-backend
uv run python manage.py migrate iams      # applies 0008 + 0009
uv run pytest iams/tests/test_audit_trail.py -v
# 13/13 pass

# Smoke-test in the API:
docker compose up
# 1. POST /api/audits/ → row created, AuditLogEntry row appears
# 2. PATCH /api/audits/<id>/ {"status": "In Progress"} → diff entry
# 3. DELETE /api/audits/<id>/ → snapshot entry
# 4. From the Django shell: try to update an existing AuditLogEntry → PermissionError
#    (Postgres in container also rejects raw UPDATE via the trigger)
```

```bash
cd iams-frontend
npm run dev
# Open /audit-log → filter by action, click a row → see the new
# AuditChangesViewer rendering the structured diff inside the detail Sheet.
```

---

## What's next: Phase 2 Track 2

**Notifications + email dispatch pipeline**:
1. `NotificationPreference` model — per-user, per-type opt-in for in-app + email.
2. Celery beat schedule: CAP-overdue nightly, weekly digest Mondays, MFA reminders.
3. `iams.tasks.notify` — fan-out from a single notification event into the user's `Notification` row + an email if their preferences say so.
4. FE: existing `NotificationsTab` becomes a preference editor; topbar bell polls `/notifications/` every 60s.

After Track 2, **Track 3** wires the approval workflow engine with escalation timers — completing Phase 2.

---

*Generated 2026-05-12.*
