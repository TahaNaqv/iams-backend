"""Domain signals that fan out into ``iams.notifications.dispatch``.

Connected in ``IamsConfig.ready()`` (see ``iams/apps.py``). Signals run
regardless of how the row was created — API, admin, seed script, raw
ORM call — so notifications can't be bypassed by entry point.

Each handler is defensive: any exception is logged but never raised, so
a failed notification cannot block the underlying save.
"""
from __future__ import annotations

import logging

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from iams.models import (
    ApprovalRequest,
    ApprovalStep,
    Audit,
    AuditAssignment,
    CorrectiveAction,
    Finding,
    Notification,
)
from iams.notifications import dispatch
from iams.tasks.notify import _resolve_user_from_owner_label

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# CAP created → notify owner
# ──────────────────────────────────────────────────────────────────────
@receiver(post_save, sender=CorrectiveAction, dispatch_uid="iams_cap_post_save_notify")
def cap_created_notify_owner(sender, instance: CorrectiveAction, created: bool, **kwargs):
    if not created:
        return
    try:
        owner = _resolve_user_from_owner_label(instance.owner)
        if owner is None:
            return
        dispatch(
            recipient=owner,
            kind=Notification.KIND_CAP_ASSIGNED,
            title=f"CAP assigned: {instance.title}",
            message=(
                f"You've been assigned a corrective action. "
                f"Due {instance.due_date.isoformat() if instance.due_date else 'TBD'}."
            ),
            level=Notification.LEVEL_ACTION,
            target=instance,
            link=f"/cap/{instance.pk}",
            module="CAPs",
        )
    except Exception:  # noqa: BLE001
        logger.exception("notify: CAP created handler failed", extra={"cap_id": str(instance.pk)})


# ──────────────────────────────────────────────────────────────────────
# Finding raised → notify owner + audit lead
# ──────────────────────────────────────────────────────────────────────
@receiver(post_save, sender=Finding, dispatch_uid="iams_finding_post_save_notify")
def finding_raised_notify(sender, instance: Finding, created: bool, **kwargs):
    if not created:
        return
    try:
        # Severity ↑ → urgency ↑
        level = (
            Notification.LEVEL_WARNING
            if instance.severity in ("Critical", "High")
            else Notification.LEVEL_INFO
        )
        message = (
            f"A {instance.severity.lower()} finding has been raised on "
            f"{instance.audit.title if instance.audit_id else 'an audit'}."
        )

        owner = _resolve_user_from_owner_label(instance.owner)
        if owner is not None:
            dispatch(
                recipient=owner,
                kind=Notification.KIND_FINDING_RAISED,
                title=f"Finding raised: {instance.title}",
                message=message,
                level=level,
                target=instance,
                link=f"/finding/{instance.pk}",
                module="Findings",
            )

        # Also tap the audit lead if they are a distinct user.
        if instance.audit_id and instance.audit and instance.audit.lead_auditor:
            lead = _resolve_user_from_owner_label(instance.audit.lead_auditor)
            if lead is not None and (owner is None or lead.pk != owner.pk):
                dispatch(
                    recipient=lead,
                    kind=Notification.KIND_FINDING_RAISED,
                    title=f"Finding raised on your audit: {instance.title}",
                    message=message,
                    level=level,
                    target=instance,
                    link=f"/finding/{instance.pk}",
                    module="Findings",
                )
    except Exception:  # noqa: BLE001
        logger.exception("notify: Finding created handler failed", extra={"finding_id": str(instance.pk)})


# ──────────────────────────────────────────────────────────────────────
# Audit assignment → notify auditor
# ──────────────────────────────────────────────────────────────────────
@receiver(post_save, sender=AuditAssignment, dispatch_uid="iams_assignment_post_save_notify")
def assignment_created_notify(sender, instance: AuditAssignment, created: bool, **kwargs):
    if not created:
        return
    try:
        if not instance.auditor or not getattr(instance.auditor, "email", ""):
            return
        user = _resolve_user_from_owner_label(instance.auditor.email)
        if user is None:
            return
        dispatch(
            recipient=user,
            kind=Notification.KIND_AUDIT_ASSIGNED,
            title=f"Audit assignment: {instance.audit.title if instance.audit_id else 'an audit'}",
            message=(
                f"You've been assigned to phase '{instance.phase}' "
                f"at {instance.allocation_pct}% allocation, "
                f"{instance.start_date} – {instance.end_date}."
            ),
            level=Notification.LEVEL_ACTION,
            target=instance.audit if instance.audit_id else None,
            link=f"/audit/{instance.audit_id}" if instance.audit_id else "",
            module="Audits",
        )
    except Exception:  # noqa: BLE001
        logger.exception("notify: AuditAssignment created handler failed")


# ──────────────────────────────────────────────────────────────────────
# Approval workflow notifications
# ──────────────────────────────────────────────────────────────────────
@receiver(post_save, sender=ApprovalRequest, dispatch_uid="iams_approval_post_save_notify")
def approval_request_notify(sender, instance: ApprovalRequest, created: bool, **kwargs):
    """On create, ping every Audit Manager (Phase 3 will replace this with
    the proper chain step). On status transition to Approved/Rejected,
    ping the submitter."""
    try:
        if created:
            # Wait for steps to be attached before figuring out who to ping.
            return
        if instance.status == "Approved":
            submitter = _resolve_user_from_owner_label(instance.submitted_by)
            if submitter:
                dispatch(
                    recipient=submitter,
                    kind=Notification.KIND_APPROVAL_APPROVED,
                    title=f"Approved: {instance.title}",
                    message=f"Your '{instance.type}' request has been approved.",
                    level=Notification.LEVEL_INFO,
                    target=instance,
                    link="/approvals",
                    module="Approvals",
                )
        elif instance.status == "Rejected":
            submitter = _resolve_user_from_owner_label(instance.submitted_by)
            if submitter:
                dispatch(
                    recipient=submitter,
                    kind=Notification.KIND_APPROVAL_REJECTED,
                    title=f"Rejected: {instance.title}",
                    message=f"Your '{instance.type}' request has been rejected.",
                    level=Notification.LEVEL_WARNING,
                    target=instance,
                    link="/approvals",
                    module="Approvals",
                )
    except Exception:  # noqa: BLE001
        logger.exception("notify: ApprovalRequest handler failed")


@receiver(post_save, sender=ApprovalStep, dispatch_uid="iams_approval_step_post_save_notify")
def approval_step_assigned_notify(sender, instance: ApprovalStep, created: bool, **kwargs):
    """When a step is created and is the next pending one, ping its approver."""
    if not created:
        return
    try:
        if instance.status != "Pending":
            return
        approver = _resolve_user_from_owner_label(instance.approver)
        if approver is None:
            return
        req = instance.request
        dispatch(
            recipient=approver,
            kind=Notification.KIND_APPROVAL_REQUESTED,
            title=f"Approval needed: {req.title}",
            message=(
                f"You're the '{instance.role}' approver on this {req.type} request "
                f"(step {instance.order + 1})."
            ),
            level=Notification.LEVEL_ACTION,
            target=req,
            link="/approvals",
            module="Approvals",
        )
    except Exception:  # noqa: BLE001
        logger.exception("notify: ApprovalStep handler failed")
