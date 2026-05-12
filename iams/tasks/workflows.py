"""Scheduled approval-workflow tasks.

The escalation scan runs nightly. For every pending step whose ``due_at``
is in the past (and which hasn't been escalated in the last 24 hours):

  1. The step's ``escalated_at`` timestamp is stamped.
  2. The originally-designated approver gets a fresh ``approval_requested``
     reminder (now flagged as escalated).
  3. Every active user holding the **Audit Manager** role gets a
     ``generic`` heads-up so escalations don't fall through the cracks.
  4. An ``approval_step_escalated`` signal is sent so future consumers
     can extend behavior (e.g. auto-skip to next role).

The task is idempotent: re-running within the 24-hour dedupe window is
a no-op.
"""
from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="iams.workflows.escalate_overdue_steps")
def escalate_overdue_steps() -> dict[str, Any]:
    """Nightly scan: notify on every overdue pending approval step."""
    # Imports deferred so Celery autodiscovery doesn't trigger app-loading
    # before Django is fully initialised.
    from iams.audit import record_audit_event
    from iams.models import ApprovalStep, AuditLogEntry, Notification
    from iams.notifications import dispatch, dispatch_to_role
    from iams.tasks.notify import _resolve_user_from_owner_label
    from iams.workflows import approval_step_escalated, overdue_pending_steps

    now = timezone.now()
    escalated = 0
    rows = list(overdue_pending_steps())  # materialize before we mutate

    for step in rows:
        days_overdue = (now - step.due_at).days if step.due_at else 0
        req = step.request
        step.escalated_at = now
        step.save(update_fields=["escalated_at"])

        # 1) Re-ping the original approver (with escalated wording).
        approver = _resolve_user_from_owner_label(step.approver) if step.approver else None
        if approver is not None:
            dispatch(
                recipient=approver,
                kind=Notification.KIND_APPROVAL_REQUESTED,
                title=f"ESCALATED — Approval still needed: {req.title}",
                message=(
                    f"You're {days_overdue} day(s) past the SLA on your "
                    f"'{step.role}' step for this {req.type} request. "
                    "Audit Managers have been notified."
                ),
                level=Notification.LEVEL_WARNING,
                target=req,
                link="/approvals",
                module="Approvals",
            )

        # 2) Manager heads-up so escalations don't get lost.
        dispatch_to_role(
            role_name="Audit Manager",
            kind=Notification.KIND_GENERIC,
            title=f"Approval escalation: {req.title}",
            message=(
                f"Step '{step.role}' is {days_overdue} day(s) overdue "
                f"on this {req.type} request."
            ),
            level=Notification.LEVEL_WARNING,
            target=req,
            link="/approvals",
            module="Approvals",
        )

        # 3) Audit log — escalations are first-class trail events.
        record_audit_event(
            action=AuditLogEntry.ACTION_OTHER,
            actor="system:escalation",
            target=req,
            details={
                "event": "approval_step_escalated",
                "step_order": step.order,
                "step_role": step.role,
                "days_overdue": days_overdue,
            },
        )

        # 4) Signal for downstream consumers.
        approval_step_escalated.send(
            sender=ApprovalStep, instance=step, days_overdue=days_overdue
        )

        escalated += 1

    logger.info("workflows.escalate_overdue_steps: escalated %d step(s)", escalated)
    return {"escalated": escalated}
