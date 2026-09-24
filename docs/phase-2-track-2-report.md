# Phase 2 Track 2 — Notifications + Email Pipeline (Complete)

**Date:** 2026-05-12
**Plan reference:** [`IMPLEMENTATION-PLAN.md`](../IMPLEMENTATION-PLAN.md) §Phase 2 Track 2
**Status:** ✅ Complete

The second of three Phase 2 cross-cutting tracks. Notifications now flow through a single central dispatcher that respects per-user, per-kind preferences and fans out to both in-app rows and email.

---

## What shipped

### Backend

**Models** ([migration 0010](../iams-backend/iams/migrations/0010_notification_email_sent_at_notification_kind_and_more.py))
- `Notification` extended with: `recipient` FK (NULL = broadcast), `kind` (14-value taxonomy), `target_content_type` + `target_object_id` GenericFK, `link`, `module`, `email_sent_at`, indexes for the FE bell query path.
- `NotificationPreference` — per-user × per-kind in-app/email toggles with a unique constraint on `(user, kind)`.

**Central dispatcher** [`iams/notifications.py`](../iams-backend/iams/notifications.py)
- `dispatch(recipient=, kind=, title=, message=, ...)` — single entry point that resolves user prefs (with sane `DEFAULT_PREFS` per kind), writes in-app row if enabled, enqueues email task if enabled. Never raises into the caller.
- `dispatch_to_role(role_name=, ...)` — fan-out helper used by escalation flows.
- 14 default-preference rows defined inline — critical events default ON for both channels, noisy events stay in-app only.
- Per-kind email subject templates.

**Email worker** [`iams/tasks/notify.py`](../iams-backend/iams/tasks/notify.py)
- `deliver_email` Celery task — autoretries (3× exponential backoff), marks `Notification.email_sent_at` on success.
- Email templates at `iams/templates/iams/email/notification.{txt,html}`.

**Scheduled tasks** (Celery beat, configured in `config/settings/base.py`)
- `iams.notify.cap_overdue_scan` — nightly 02:00. Walks open CAPs, notifies owners about overdue + due-in-3-days. Deduped 24h per CAP.
- `iams.notify.weekly_digest` — Mondays 08:00. Personalised summary per active user.

**Signal handlers** [`iams/signals.py`](../iams-backend/iams/signals.py)
- `CorrectiveAction.post_save` → notify owner on create
- `Finding.post_save` → notify owner + audit lead on create (severity-aware level)
- `AuditAssignment.post_save` → notify assigned auditor
- `ApprovalRequest.post_save` → notify submitter on approved/rejected
- `ApprovalStep.post_save` → notify approver when their pending step appears

Wired via `IamsConfig.ready()` so they fire whether the row was created via API, admin, or seed script.

**API**
- `GET /api/notifications/` — **per-user scoped** (plus `recipient=NULL` broadcasts). Filterable by `kind` and `read`.
- `GET /api/notifications/unread-count/` — minimal endpoint for the FE bell badge.
- `GET /api/notification-preferences/` — returns one row per kind: stored rows for kinds the user customised, defaults for the rest (server-side merge so the FE matrix is always complete on first paint).
- `POST /api/notification-preferences/` — upsert by `kind`.

**Tests** ([`iams/tests/test_notifications.py`](../iams-backend/iams/tests/test_notifications.py) — 22 tests)
- Dispatcher (pref-gated in-app + email, broadcast handling, error swallow)
- Every signal handler (CAP, Finding, audit-lead-distinct-from-owner, assignment, approval requested/approved/rejected)
- Beat tasks (overdue + due-soon, dedupe-per-24h, weekly digest fan-out)
- API: per-user scoping, broadcast inclusion, unread count, preference list-with-defaults, upsert
- `dispatch_to_role` fan-out

### Frontend

**`src/lib/notifications-api.ts`**
- Typed client for `/api/notification-preferences/`
- `KIND_METADATA` — human label + group + description for the full backend taxonomy (used by the preferences editor)
- `getUnreadNotificationCount()` for the bell badge

**`src/hooks/use-data.ts`**
- `useNotifications` now polls every 60 seconds (`refetchInterval: 60_000`, `staleTime: 30_000`). Background-tab polling disabled.

**`src/components/settings/NotificationsTab.tsx`** rewritten
- Two-column toggle matrix (in-app × email) over the full 14-kind taxonomy
- Grouped: Audits / Findings / CAPs / Approvals / Account / Digest
- Skeleton loading, optimistic toggle with toast-on-failure rollback
- Per-row `disabled` while in-flight
- Descriptive subtitles per kind

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
| **Backend notifications (new)** | **22** |
| Backend legacy domain | 3 |
| **Backend total** | **339** |
| Frontend vitest | 14 |

---

## Acceptance criteria (from plan §Phase 2 Track 2)

| Criterion | Status |
|---|---|
| Celery + Redis broker | ✅ (from Phase 0) |
| Email backend via `django-anymail` SMTP | ✅ (mailhog in dev, SMTP relay in prod) |
| 14-kind notification taxonomy | ✅ |
| Each notification: row + email (pref-gated) | ✅ |
| User notification preferences (per-type opt-in) | ✅ |
| Celery beat: nightly CAP-overdue scan | ✅ (with 24h dedupe) |
| Celery beat: weekly digest Mondays 08:00 | ✅ |
| FE: NotificationsTab is a preference editor | ✅ |
| FE: topbar bell wired to real `/notifications/` | ✅ (polled every 60s) |

---

## How to verify locally

```bash
cd iams-backend
uv run python manage.py migrate iams           # applies 0010
uv run pytest iams/tests/test_notifications.py -v   # 22/22

# Boot the stack
docker compose up
# Trigger a notification end-to-end:
# 1. POST /api/findings/ with severity=Critical and an owner that maps to a user → in-app row + email to mailhog
# 2. Open http://localhost:8025 to see the email arrive

# Beat verification (without waiting until 02:00):
docker compose exec backend uv run python manage.py shell -c "from iams.tasks.notify import dispatch_cap_overdue_reminders; print(dispatch_cap_overdue_reminders())"
```

```bash
cd iams-frontend
npm run dev
# Visit /settings → Notifications tab — toggle a row, watch the optimistic
# update + POST to /api/notification-preferences/. Then open the topbar bell;
# new notifications appear within 60s without reload.
```

---

## Known follow-ups (parked into Phase 5)

- **WebSocket push** for the FE bell — currently polls every 60s. Phase 5 observability work introduces channels for real-time delivery.
- **SMS / push** channels — model is currently in-app + email only. Phase 6 SSO/integrations work adds Twilio + APNs.
- **Notification retention** — every row currently lives forever. Phase 5 hardening adds a retention task (drop in-app rows older than 90d; keep `email_sent_at` audit traces).

---

## What's next: Phase 2 Track 3

**Approval workflow engine** is the final Phase 2 piece:
1. Configurable approval chain templates (Auditor → Manager → CAE → Board) with per-org overrides.
2. Escalation timer — if a step is unactioned for N days, escalate to the next role + email the manager.
3. Signal-driven side effects when an approval completes (audit plan approved → audits become creatable; CAP closure approved → finding can close).
4. FE: `WorkflowApprovals` page wired to real data, "my pending approvals" on the dashboard.

After Track 3, Phase 2 closes and Phase 3 (Working Papers, QAIP, CSA, ICFR — the four major missing modules) begins.

---

*Generated 2026-05-12.*
