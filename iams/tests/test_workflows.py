"""Tests for the approval workflow engine.

Coverage:
  - Chain template auto-applies on ApprovalRequest create.
  - Approve advances through multi-step chains.
  - Reject short-circuits and emits the rejected signal.
  - Approver authorisation: only the designated approver / matching role /
    super-admin can action a step.
  - Escalation Celery task notifies + stamps + dedupes per 24h.
  - ``?mine=pending`` filter is correctly scoped.
  - Domain side effects fire on completion (CAP closure → CAP closed).
"""
from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from freezegun import freeze_time

from iams.models import (
    ApprovalChainTemplate,
    ApprovalRequest,
    ApprovalStep,
    Audit,
    AuditLogEntry,
    CorrectiveAction,
    Finding,
    Notification,
)
from iams.tasks.workflows import escalate_overdue_steps
from iams.workflows import (
    ApprovalError,
    advance_on_approve,
    apply_chain_template,
    can_user_action,
    reject_request,
)

pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def audit_plan_chain():
    return ApprovalChainTemplate.objects.create(
        name="Audit Plan default",
        request_type="Audit Plan",
        chain=[
            {"role": "Audit Manager", "sla_days": 3},
            {"role": "CAE", "sla_days": 5},
            {"role": "Board", "sla_days": 14},
        ],
        is_active=True,
    )


@pytest.fixture
def make_request():
    def _make(kind: str = "Audit Plan", submitted_by: str = "alice", title="X"):
        return ApprovalRequest.objects.create(
            title=title, type=kind, reference_id="",
            department="IA", submitted_by=submitted_by,
            submitted_date=date.today(), current_step=0,
            priority="High", description="…", status="Pending",
        )
    return _make


# ══════════════════════════════════════════════════════════════════════
# Chain template application
# ══════════════════════════════════════════════════════════════════════
def test_chain_template_auto_applies_on_create(audit_plan_chain):
    req = ApprovalRequest.objects.create(
        title="Q1 plan", type="Audit Plan", reference_id="",
        department="IA", submitted_by="alice",
        submitted_date=date.today(), current_step=0,
        priority="High", description="…", status="Pending",
    )
    steps = list(req.steps.order_by("order"))
    assert len(steps) == 3
    assert [s.role for s in steps] == ["Audit Manager", "CAE", "Board"]
    assert steps[0].sla_days == 3
    assert steps[0].due_at is not None  # first step has due_at set
    assert steps[1].due_at is None      # later steps get due_at when activated


def test_chain_template_inactive_does_not_apply(audit_plan_chain):
    audit_plan_chain.is_active = False
    audit_plan_chain.save(update_fields=["is_active"])
    req = ApprovalRequest.objects.create(
        title="X", type="Audit Plan", reference_id="", department="IA",
        submitted_by="alice", submitted_date=date.today(), current_step=0,
        priority="High", description="…", status="Pending",
    )
    assert req.steps.count() == 0


def test_chain_template_does_not_overwrite_inline_steps(audit_plan_chain):
    req = ApprovalRequest.objects.create(
        title="X", type="Audit Plan", reference_id="", department="IA",
        submitted_by="alice", submitted_date=date.today(), current_step=0,
        priority="High", description="…", status="Pending",
    )
    # Initial auto-apply produced 3 steps.
    assert req.steps.count() == 3
    # Calling apply_chain_template again is a no-op.
    assert apply_chain_template(req) == 0
    assert req.steps.count() == 3


def test_only_one_active_template_per_type(audit_plan_chain):
    """The unique-active constraint prevents two simultaneous active
    templates for the same request_type."""
    with pytest.raises(Exception):  # IntegrityError
        ApprovalChainTemplate.objects.create(
            name="competing",
            request_type="Audit Plan",
            chain=[{"role": "X", "sla_days": 1}],
            is_active=True,
        )


# ══════════════════════════════════════════════════════════════════════
# Approve / reject + authorisation
# ══════════════════════════════════════════════════════════════════════
def test_approve_requires_designated_role(audit_plan_chain, make_request, auditor_user):
    req = make_request()
    # auditor_user has role "Auditor", not "Audit Manager" — should be denied
    with pytest.raises(ApprovalError, match="not the designated approver"):
        advance_on_approve(req, by_user=auditor_user, comment="lgtm")


def test_approve_allowed_when_role_matches(audit_plan_chain, make_request, audit_manager):
    req = make_request()
    # audit_manager has role "Audit Manager" — matches step 1 ("Audit Manager")
    advance_on_approve(req, by_user=audit_manager, comment="ok")
    step1 = req.steps.get(order=0)
    assert step1.status == "Approved"
    # Still pending overall — 2 more steps remain.
    req.refresh_from_db()
    assert req.status == "Pending"
    assert req.current_step == 1


def test_super_admin_can_action_any_step(audit_plan_chain, make_request, super_admin):
    req = make_request()
    advance_on_approve(req, by_user=super_admin, comment="forced")
    assert req.steps.get(order=0).status == "Approved"


def test_approve_advances_through_multistep_chain(audit_plan_chain, make_request, super_admin):
    req = make_request()
    # Super admin can step through all three.
    advance_on_approve(req, by_user=super_admin)
    advance_on_approve(req, by_user=super_admin)
    advance_on_approve(req, by_user=super_admin)
    req.refresh_from_db()
    assert req.status == "Approved"
    assert all(s.status == "Approved" for s in req.steps.all())


def test_reject_short_circuits_remaining_steps(audit_plan_chain, make_request, audit_manager):
    req = make_request()
    reject_request(req, by_user=audit_manager, comment="no")
    req.refresh_from_db()
    assert req.status == "Rejected"
    step1 = req.steps.get(order=0)
    assert step1.status == "Rejected"
    # Later steps remain in Pending — the request status is what gates further action.
    assert req.steps.filter(order=1).first().status == "Pending"


def test_approve_promotes_next_step_due_at(audit_plan_chain, make_request, super_admin):
    req = make_request()
    advance_on_approve(req, by_user=super_admin)
    step2 = req.steps.get(order=1)
    assert step2.due_at is not None


def test_can_user_action_returns_step_even_when_disallowed(audit_plan_chain, make_request, auditor_user):
    req = make_request()
    allowed, step = can_user_action(req, auditor_user)
    assert allowed is False
    assert step is not None
    assert step.order == 0


# ══════════════════════════════════════════════════════════════════════
# Domain side effects on completion
# ══════════════════════════════════════════════════════════════════════
def test_cap_closure_approval_closes_the_cap(make_request, super_admin):
    audit = Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date.today(), end_date=date.today() + timedelta(days=30),
        scope="s", objectives="o", completion_percent=50, findings_count=1,
    )
    finding = Finding.objects.create(
        audit=audit, title="F", department="F", severity="High",
        status="Open", owner="o",
        due_date=date.today() + timedelta(days=14),
        description="d", root_cause="rc", recommendation="r",
        created_date=date.today(),
    )
    cap = CorrectiveAction.objects.create(
        finding=finding, title="Fix it", owner="o",
        due_date=date.today() + timedelta(days=30),
        status="In Progress", priority="High",
        description="…", progress=80, department="F",
    )
    # Use a 1-step chain via inline steps (no template needed)
    req = ApprovalRequest.objects.create(
        title="Close CAP", type="CAP Closure", reference_id=str(cap.pk),
        department="F", submitted_by=super_admin.email,
        submitted_date=date.today(), current_step=0,
        priority="High", description="…", status="Pending",
    )
    ApprovalStep.objects.create(
        request=req, order=0, role="Audit Manager", approver=super_admin.email,
        status="Pending",
    )

    advance_on_approve(req, by_user=super_admin)
    cap.refresh_from_db()
    assert cap.status == "Closed"
    assert cap.progress == 100


# ══════════════════════════════════════════════════════════════════════
# Escalation Celery task
# ══════════════════════════════════════════════════════════════════════
def test_escalation_picks_up_overdue_pending_steps(audit_plan_chain, make_request, audit_manager):
    """A step whose due_at is in the past should escalate; recent steps should not."""
    req = make_request()
    step1 = req.steps.get(order=0)
    # Force it overdue
    step1.due_at = timezone.now() - timedelta(days=2)
    step1.escalated_at = None
    step1.save(update_fields=["due_at", "escalated_at"])

    Notification.objects.all().delete()
    result = escalate_overdue_steps()
    assert result["escalated"] == 1

    step1.refresh_from_db()
    assert step1.escalated_at is not None

    # Original approver should be re-pinged with the escalated wording…
    # (audit_manager doesn't match step1.approver here — no email set —
    # so only the role-fan-out broadcast fires)
    manager_notifs = Notification.objects.filter(
        recipient=audit_manager, kind=Notification.KIND_GENERIC,
    )
    assert manager_notifs.exists()


def test_escalation_is_deduped_per_24h(audit_plan_chain, make_request):
    req = make_request()
    step1 = req.steps.get(order=0)
    step1.due_at = timezone.now() - timedelta(days=2)
    step1.escalated_at = None
    step1.save(update_fields=["due_at", "escalated_at"])

    first = escalate_overdue_steps()
    second = escalate_overdue_steps()
    assert first["escalated"] == 1
    assert second["escalated"] == 0


def test_escalation_records_audit_log_event(audit_plan_chain, make_request):
    req = make_request()
    step1 = req.steps.get(order=0)
    step1.due_at = timezone.now() - timedelta(days=2)
    step1.escalated_at = None
    step1.save(update_fields=["due_at", "escalated_at"])

    AuditLogEntry.objects.all().delete()
    escalate_overdue_steps()
    entry = AuditLogEntry.objects.filter(
        details__event="approval_step_escalated"
    ).first()
    assert entry is not None
    assert entry.actor == "system:escalation"


def test_escalation_skips_steps_with_future_due_at(audit_plan_chain, make_request):
    req = make_request()
    step1 = req.steps.get(order=0)
    # due_at in the future → not eligible
    step1.due_at = timezone.now() + timedelta(days=1)
    step1.save(update_fields=["due_at"])

    result = escalate_overdue_steps()
    assert result["escalated"] == 0


# ══════════════════════════════════════════════════════════════════════
# ?mine=pending filter
# ══════════════════════════════════════════════════════════════════════
def test_mine_pending_returns_only_user_or_role_steps(
    audit_plan_chain, make_request, audit_manager, auditor_user, authed_client,
):
    """Audit Manager should see Audit-Plan requests with a pending step
    matching their role; Auditor should see none of them."""
    make_request(title="Plan 1")
    make_request(title="Plan 2")

    mgr_client = authed_client(audit_manager)
    response = mgr_client.get("/api/approval-requests/?mine=pending")
    assert response.status_code == 200
    body = response.json()
    results = body.get("results", body) if isinstance(body, dict) else body
    titles = [r["title"] for r in results]
    assert "Plan 1" in titles
    assert "Plan 2" in titles

    aud_client = authed_client(auditor_user)
    response2 = aud_client.get("/api/approval-requests/?mine=pending")
    body2 = response2.json()
    results2 = body2.get("results", body2) if isinstance(body2, dict) else body2
    assert results2 == []


# ══════════════════════════════════════════════════════════════════════
# API: approve / reject 400s on wrong approver
# ══════════════════════════════════════════════════════════════════════
def test_api_approve_400_for_wrong_approver(audit_plan_chain, make_request, auditor_user, authed_client):
    req = make_request()
    client = authed_client(auditor_user)
    response = client.post(
        f"/api/approval-requests/{req.id}/approve/",
        {"comments": "anyway"}, format="json",
    )
    assert response.status_code == 400
    assert "not the designated approver" in response.json()["detail"]


def test_api_approve_records_audit_log(audit_plan_chain, make_request, audit_manager, authed_client):
    req = make_request()
    AuditLogEntry.objects.filter(action="approve").delete()
    client = authed_client(audit_manager)
    response = client.post(
        f"/api/approval-requests/{req.id}/approve/",
        {"comments": "LGTM"}, format="json",
    )
    assert response.status_code == 200
    entry = AuditLogEntry.objects.filter(action="approve").order_by("-timestamp").first()
    assert entry is not None
    assert entry.actor == audit_manager.email
    assert entry.details["step_role"] == "Audit Manager"
    assert entry.details["comments"] == "LGTM"
