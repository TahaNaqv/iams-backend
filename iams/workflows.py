"""Approval workflow engine.

A single place for the side-effecting verbs that operate on
``ApprovalRequest`` rows: applying a chain template, advancing on
approve, short-circuiting on reject, dispatching escalations, and
emitting domain-specific completion signals.

The viewset action handlers (``ApprovalRequestViewSet.approve`` and
``.reject``) call into ``advance_on_approve`` / ``reject_request`` so
the business logic isn't duplicated across HTTP, admin, and Celery
contexts.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Iterable

from django.contrib.auth import get_user_model
from django.db import transaction
from django.dispatch import Signal
from django.utils import timezone

from iams.models import ApprovalChainTemplate, ApprovalRequest, ApprovalStep

logger = logging.getLogger(__name__)
User = get_user_model()


# ──────────────────────────────────────────────────────────────────────
# Signals: domain-specific consumers wire to these to take action when
# an approval workflow completes. (E.g., ``audit_plan_approved`` → unlock
# audits for the year; ``cap_closure_approved`` → mark the CAP closed.)
# Wired in iams/signals.py.
# ──────────────────────────────────────────────────────────────────────
approval_request_approved = Signal()  # sender=ApprovalRequest, instance=request
approval_request_rejected = Signal()  # sender=ApprovalRequest, instance=request
approval_step_escalated = Signal()    # sender=ApprovalStep,    instance=step, days_overdue=int


class ApprovalError(Exception):
    """Domain error from the approval workflow (e.g., wrong approver)."""


# ──────────────────────────────────────────────────────────────────────
# Chain application
# ──────────────────────────────────────────────────────────────────────
def apply_chain_template(request: ApprovalRequest) -> int:
    """Expand the active chain template for ``request.type`` into steps.

    No-op if the request already has at least one step, or if no active
    template exists for the type. Returns the number of steps created.
    """
    if request.steps.exists():
        return 0
    template = ApprovalChainTemplate.objects.filter(
        request_type=request.type, is_active=True
    ).first()
    if template is None:
        return 0
    descriptors = template.step_descriptors()
    if not descriptors:
        return 0

    now = timezone.now()
    created = 0
    for order, descriptor in enumerate(descriptors):
        sla_days = descriptor["sla_days"]
        # Due date is computed from "right now" when the step is first
        # eligible (i.e., when it becomes the current step). For now we
        # set it for the first step only — subsequent steps get their
        # due_at when they become current.
        ApprovalStep.objects.create(
            request=request,
            order=order,
            role=descriptor["role"],
            sla_days=sla_days,
            due_at=(now + timedelta(days=sla_days)) if order == 0 else None,
        )
        created += 1
    logger.info(
        "approval: applied chain template '%s' (%d steps) to request %s",
        template.name, created, request.pk,
    )
    return created


# ──────────────────────────────────────────────────────────────────────
# Authorisation: who is the current approver?
# ──────────────────────────────────────────────────────────────────────
def current_step(request: ApprovalRequest) -> ApprovalStep | None:
    """Return the next pending step, or None if the request is fully actioned."""
    return request.steps.filter(status="Pending").order_by("order").first()


def can_user_action(request: ApprovalRequest, user: User) -> tuple[bool, ApprovalStep | None]:
    """Determine if ``user`` is eligible to approve/reject the current step.

    Eligibility rules (in order):
      1. The current step's ``approver`` email matches ``user.email`` exactly.
      2. The user holds the role named in the step's ``role`` field.
      3. The user's role is ``Super Admin`` (bypass).

    Returns ``(allowed, current_step)``. If no pending step exists, both
    return values reflect that: ``(False, None)``.
    """
    step = current_step(request)
    if step is None or not user or not user.is_authenticated:
        return False, step

    if step.approver and user.email and step.approver.lower() == user.email.lower():
        return True, step

    profile = getattr(user, "profile", None)
    if profile is None or profile.role is None:
        return False, step

    role = profile.role
    if role.is_super_admin:
        return True, step
    if step.role and role.name.strip().lower() == step.role.strip().lower():
        return True, step

    return False, step


# ──────────────────────────────────────────────────────────────────────
# Approve / reject
# ──────────────────────────────────────────────────────────────────────
@transaction.atomic
def advance_on_approve(
    request: ApprovalRequest, *, by_user: User, comment: str = ""
) -> ApprovalRequest:
    """Mark the current step approved and advance.

    If the approved step was the last pending one (and nothing was rejected),
    the request transitions to ``Approved`` and the ``approval_request_approved``
    signal fires.
    """
    allowed, step = can_user_action(request, by_user)
    if step is None:
        raise ApprovalError("No pending step on this request.")
    if not allowed:
        raise ApprovalError("You are not the designated approver for this step.")

    step.status = "Approved"
    step.date = timezone.now().date()
    step.comments = comment or "Approved."
    step.save(update_fields=["status", "date", "comments"])

    # Promote the next pending step's due_at to "starting now".
    next_step = current_step(request)
    if next_step is not None and next_step.due_at is None:
        next_step.due_at = timezone.now() + timedelta(days=next_step.sla_days or 7)
        next_step.save(update_fields=["due_at"])

    request.current_step = min(request.current_step + 1, request.steps.count())
    request.last_action_at = timezone.now()
    request.save(update_fields=["current_step", "last_action_at"])

    # If no more pending and no rejected → fully approved.
    if (
        not request.steps.filter(status="Pending").exists()
        and not request.steps.filter(status="Rejected").exists()
    ):
        request.status = "Approved"
        request.save(update_fields=["status"])
        approval_request_approved.send(sender=ApprovalRequest, instance=request)

    return request


@transaction.atomic
def reject_request(
    request: ApprovalRequest, *, by_user: User, comment: str = ""
) -> ApprovalRequest:
    """Reject the current step → reject the whole request."""
    allowed, step = can_user_action(request, by_user)
    if step is None:
        raise ApprovalError("No pending step on this request.")
    if not allowed:
        raise ApprovalError("You are not the designated approver for this step.")

    step.status = "Rejected"
    step.date = timezone.now().date()
    step.comments = comment or "Rejected."
    step.save(update_fields=["status", "date", "comments"])

    request.status = "Rejected"
    request.last_action_at = timezone.now()
    request.save(update_fields=["status", "last_action_at"])
    approval_request_rejected.send(sender=ApprovalRequest, instance=request)

    return request


# ──────────────────────────────────────────────────────────────────────
# Escalation: overdue pending steps
# ──────────────────────────────────────────────────────────────────────
def overdue_pending_steps(*, dedupe_hours: int = 24) -> Iterable[ApprovalStep]:
    """Generator of pending steps that have passed ``due_at`` and have
    not been escalated within the last ``dedupe_hours`` window.

    Pure read — does not mutate. The escalation Celery task wraps this
    with the actual notification + audit-log dispatch.
    """
    now = timezone.now()
    cutoff = now - timedelta(hours=dedupe_hours)
    qs = (
        ApprovalStep.objects
        .select_related("request")
        .filter(status="Pending", due_at__lt=now)
        .filter(
            # Either never escalated, or last escalated more than dedupe ago.
            models_q_escalated_recent(cutoff)
        )
        .order_by("due_at")
    )
    return qs


def models_q_escalated_recent(cutoff):
    """Q-fragment: step has never escalated, or escalated_at < cutoff."""
    from django.db.models import Q
    return Q(escalated_at__isnull=True) | Q(escalated_at__lt=cutoff)
