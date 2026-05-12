"""Tests for the notification dispatch pipeline.

Coverage:
  - Dispatcher writes in-app row when pref allows; suppresses when not.
  - Dispatcher enqueues email when email-pref allows; suppresses when not.
  - System-wide broadcast (recipient=None) is allowed and never emails.
  - Signals fire on CAP / Finding / Audit assignment / Approval transitions.
  - Beat tasks (`cap_overdue_scan`, `weekly_digest`) produce expected output
    and don't re-fire when run a second time within 24h.
  - `/api/notifications/` is per-user scoped, includes system broadcasts.
  - `/api/notification-preferences/` returns merged defaults + stored rows.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from freezegun import freeze_time

from iams.models import (
    ApprovalRequest,
    ApprovalStep,
    Audit,
    AuditAssignment,
    Auditor,
    CorrectiveAction,
    Finding,
    Notification,
    NotificationPreference,
    UserProfile,
)
from iams.notifications import dispatch, dispatch_to_role
from iams.tasks.notify import (
    dispatch_cap_overdue_reminders,
    dispatch_weekly_digest,
)

User = get_user_model()
pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def audit() -> Audit:
    return Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )


# ══════════════════════════════════════════════════════════════════════
# Dispatcher
# ══════════════════════════════════════════════════════════════════════
def test_dispatch_writes_in_app_row_and_email_with_defaults(auditor_user, audit):
    mail.outbox.clear()
    notif = dispatch(
        recipient=auditor_user,
        kind=Notification.KIND_CAP_ASSIGNED,
        title="CAP assigned: X",
        message="You own it now.",
        target=audit,
        link="/cap/123",
        module="CAPs",
    )
    assert notif is not None
    assert notif.recipient == auditor_user
    assert notif.kind == "cap_assigned"
    assert notif.title == "CAP assigned: X"
    assert notif.link == "/cap/123"
    assert notif.module == "CAPs"
    # Email was queued + sent eagerly (test settings).
    assert len(mail.outbox) == 1
    assert auditor_user.email in mail.outbox[0].to
    assert "CAP assigned" in mail.outbox[0].subject


def test_dispatch_respects_user_in_app_off(auditor_user):
    mail.outbox.clear()
    NotificationPreference.objects.create(
        user=auditor_user, kind=Notification.KIND_GENERIC,
        in_app_enabled=False, email_enabled=True,
    )
    notif = dispatch(
        recipient=auditor_user,
        kind=Notification.KIND_GENERIC,
        title="Hi", message="hi",
    )
    assert notif is None  # no in-app row
    # Email still sent because email_enabled=True
    assert len(mail.outbox) == 1


def test_dispatch_respects_user_email_off(auditor_user):
    mail.outbox.clear()
    NotificationPreference.objects.create(
        user=auditor_user, kind=Notification.KIND_CAP_ASSIGNED,
        in_app_enabled=True, email_enabled=False,
    )
    notif = dispatch(
        recipient=auditor_user,
        kind=Notification.KIND_CAP_ASSIGNED,
        title="X", message="…",
    )
    assert notif is not None
    assert len(mail.outbox) == 0


def test_dispatch_respects_both_channels_off(auditor_user):
    mail.outbox.clear()
    NotificationPreference.objects.create(
        user=auditor_user, kind=Notification.KIND_AUDIT_STATUS_CHANGE,
        in_app_enabled=False, email_enabled=False,
    )
    notif = dispatch(
        recipient=auditor_user,
        kind=Notification.KIND_AUDIT_STATUS_CHANGE,
        title="X", message="…",
    )
    assert notif is None
    assert len(mail.outbox) == 0


def test_dispatch_system_broadcast_writes_row_no_email():
    mail.outbox.clear()
    notif = dispatch(
        recipient=None,
        kind=Notification.KIND_GENERIC,
        title="Maintenance window",
        message="Sunday 02:00–04:00 UTC",
    )
    assert notif is not None
    assert notif.recipient is None
    assert len(mail.outbox) == 0  # no recipient → no email


def test_dispatch_swallows_errors_does_not_raise(auditor_user, monkeypatch):
    """A bug in email delivery must not surface to the caller."""
    from iams.tasks import notify as notify_module

    def boom(*a, **kw):
        raise RuntimeError("smtp exploded")

    monkeypatch.setattr(notify_module.deliver_email, "delay", boom)
    notif = dispatch(
        recipient=auditor_user,
        kind=Notification.KIND_GENERIC,
        title="x", message="y",
    )
    # Even though email enqueue blew up, the function returned (didn't raise).
    # Whether the row was created depends on order — but no exception leaked.
    assert notif is None or isinstance(notif, Notification)


# ══════════════════════════════════════════════════════════════════════
# Signal hooks
# ══════════════════════════════════════════════════════════════════════
def test_cap_created_notifies_owner_by_email_match(audit, auditor_user):
    mail.outbox.clear()
    finding = Finding.objects.create(
        audit=audit, title="F", department="F", severity="High",
        status="Open", owner=auditor_user.email,
        due_date=date.today() + timedelta(days=10),
        description="d", root_cause="rc", recommendation="r",
        created_date=date.today(),
    )
    CorrectiveAction.objects.create(
        finding=finding, title="Deploy fix",
        owner=auditor_user.email,  # match user.email triggers resolution
        due_date=date.today() + timedelta(days=30),
        status="Open", priority="High",
        description="…", progress=0, department="F",
    )
    notif = (
        Notification.objects
        .filter(recipient=auditor_user, kind=Notification.KIND_CAP_ASSIGNED)
        .first()
    )
    assert notif is not None
    assert "CAP assigned" in notif.title


def test_finding_raised_notifies_owner(audit, auditor_user):
    Finding.objects.create(
        audit=audit, title="Wire approval gap", department="F",
        severity="Critical", status="Open", owner=auditor_user.email,
        due_date=date.today() + timedelta(days=14),
        description="d", root_cause="rc", recommendation="r",
        created_date=date.today(),
    )
    notif = (
        Notification.objects
        .filter(recipient=auditor_user, kind=Notification.KIND_FINDING_RAISED)
        .first()
    )
    assert notif is not None
    assert "Wire approval gap" in notif.title
    # Critical severity → warning level on the bell
    assert notif.type == Notification.LEVEL_WARNING


def test_finding_raised_also_notifies_audit_lead(audit, auditor_user, audit_manager):
    # Make the lead a real user resolvable by email
    audit.lead_auditor = audit_manager.email
    audit.save(update_fields=["lead_auditor"])

    Finding.objects.create(
        audit=audit, title="X", department="F", severity="High",
        status="Open", owner=auditor_user.email,
        due_date=date.today() + timedelta(days=10),
        description="d", root_cause="rc", recommendation="r",
        created_date=date.today(),
    )
    owner_notif = Notification.objects.filter(recipient=auditor_user, kind=Notification.KIND_FINDING_RAISED).first()
    lead_notif = Notification.objects.filter(recipient=audit_manager, kind=Notification.KIND_FINDING_RAISED).first()
    assert owner_notif is not None
    assert lead_notif is not None
    assert lead_notif.pk != owner_notif.pk


def test_assignment_notifies_auditor(audit, auditor_user):
    auditor_row = Auditor.objects.create(
        name="A", email=auditor_user.email, role="r",
        availability="Available", skills=[], certifications=[],
        weekly_capacity_hours=40,
    )
    AuditAssignment.objects.create(
        auditor=auditor_row, audit=audit, phase="Fieldwork",
        allocation_pct=50,
        start_date=date(2026, 2, 1), end_date=date(2026, 2, 15),
    )
    notif = Notification.objects.filter(
        recipient=auditor_user, kind=Notification.KIND_AUDIT_ASSIGNED
    ).first()
    assert notif is not None


def test_approval_step_notifies_approver(audit_manager):
    req = ApprovalRequest.objects.create(
        title="Approve plan", type="Audit Plan", reference_id="X",
        department="IA", submitted_by="alice", submitted_date=date.today(),
        current_step=0, priority="High", description="…", status="Pending",
    )
    ApprovalStep.objects.create(
        request=req, role="Manager", approver=audit_manager.email,
        status="Pending", order=0,
    )
    notif = Notification.objects.filter(
        recipient=audit_manager, kind=Notification.KIND_APPROVAL_REQUESTED
    ).first()
    assert notif is not None
    assert "Approval needed" in notif.title


def test_approval_approved_notifies_submitter(audit_manager):
    req = ApprovalRequest.objects.create(
        title="Approve plan", type="Audit Plan", reference_id="X",
        department="IA", submitted_by=audit_manager.email,
        submitted_date=date.today(), current_step=0,
        priority="High", description="…", status="Pending",
    )
    req.status = "Approved"
    req.save(update_fields=["status"])
    notif = Notification.objects.filter(
        recipient=audit_manager, kind=Notification.KIND_APPROVAL_APPROVED
    ).first()
    assert notif is not None


# ══════════════════════════════════════════════════════════════════════
# Beat tasks
# ══════════════════════════════════════════════════════════════════════
def test_cap_overdue_scan_dispatches_for_overdue_caps(audit, auditor_user):
    Notification.objects.all().delete()
    finding = Finding.objects.create(
        audit=audit, title="F", department="F", severity="High",
        status="Open", owner=auditor_user.email,
        due_date=date.today() - timedelta(days=10),
        description="d", root_cause="rc", recommendation="r",
        created_date=date.today() - timedelta(days=20),
    )
    CorrectiveAction.objects.create(
        finding=finding, title="Late CAP",
        owner=auditor_user.email,
        due_date=date.today() - timedelta(days=5),  # overdue
        status="Open", priority="High",
        description="…", progress=0, department="F",
    )
    # Wipe CAP-created assignment notifications so the count below is crisp
    Notification.objects.filter(kind=Notification.KIND_CAP_OVERDUE).delete()

    result = dispatch_cap_overdue_reminders()
    assert result["overdue"] == 1

    notif = Notification.objects.filter(
        recipient=auditor_user, kind=Notification.KIND_CAP_OVERDUE
    ).first()
    assert notif is not None
    assert "overdue" in notif.title.lower()


def test_cap_overdue_scan_is_deduped_per_24h(audit, auditor_user):
    finding = Finding.objects.create(
        audit=audit, title="F", department="F", severity="High",
        status="Open", owner=auditor_user.email,
        due_date=date.today() - timedelta(days=10),
        description="d", root_cause="rc", recommendation="r",
        created_date=date.today() - timedelta(days=20),
    )
    CorrectiveAction.objects.create(
        finding=finding, title="Late CAP",
        owner=auditor_user.email,
        due_date=date.today() - timedelta(days=5),
        status="Open", priority="High",
        description="…", progress=0, department="F",
    )
    first = dispatch_cap_overdue_reminders()
    second = dispatch_cap_overdue_reminders()
    assert first["overdue"] == 1
    assert second["overdue"] == 0  # deduped


def test_cap_due_soon_within_3_days(audit, auditor_user):
    finding = Finding.objects.create(
        audit=audit, title="F", department="F", severity="High",
        status="Open", owner=auditor_user.email,
        due_date=date.today() + timedelta(days=2),
        description="d", root_cause="rc", recommendation="r",
        created_date=date.today(),
    )
    CorrectiveAction.objects.create(
        finding=finding, title="Soon-due CAP",
        owner=auditor_user.email,
        due_date=date.today() + timedelta(days=2),  # in 2 days
        status="Open", priority="High",
        description="…", progress=0, department="F",
    )
    Notification.objects.filter(kind=Notification.KIND_CAP_DUE_SOON).delete()

    result = dispatch_cap_overdue_reminders()
    assert result["due_soon"] == 1
    notif = Notification.objects.filter(
        recipient=auditor_user, kind=Notification.KIND_CAP_DUE_SOON
    ).first()
    assert notif is not None


def test_weekly_digest_sends_one_per_active_user(audit_manager, auditor_user):
    Notification.objects.filter(kind=Notification.KIND_WEEKLY_DIGEST).delete()
    result = dispatch_weekly_digest()
    assert result["sent"] >= 2
    assert Notification.objects.filter(
        recipient=audit_manager, kind=Notification.KIND_WEEKLY_DIGEST
    ).exists()
    assert Notification.objects.filter(
        recipient=auditor_user, kind=Notification.KIND_WEEKLY_DIGEST
    ).exists()


# ══════════════════════════════════════════════════════════════════════
# API: scoping + preferences
# ══════════════════════════════════════════════════════════════════════
def test_notifications_endpoint_is_scoped_to_user(authed_client, auditor_user, audit_manager):
    Notification.objects.all().delete()
    dispatch(
        recipient=auditor_user, kind=Notification.KIND_GENERIC,
        title="for auditor", message="…",
    )
    dispatch(
        recipient=audit_manager, kind=Notification.KIND_GENERIC,
        title="for manager", message="…",
    )

    client = authed_client(auditor_user)
    response = client.get("/api/notifications/")
    assert response.status_code == 200
    body = response.json()
    rows = body["results"] if isinstance(body, dict) else body
    titles = [n["title"] for n in rows]
    assert "for auditor" in titles
    assert "for manager" not in titles


def test_notifications_endpoint_includes_broadcasts(authed_client, auditor_user):
    Notification.objects.all().delete()
    dispatch(
        recipient=None, kind=Notification.KIND_GENERIC,
        title="Maintenance", message="…",
    )
    client = authed_client(auditor_user)
    body = client.get("/api/notifications/").json()
    rows = body["results"] if isinstance(body, dict) else body
    titles = [n["title"] for n in rows]
    assert "Maintenance" in titles


def test_notifications_unread_count(authed_client, auditor_user):
    Notification.objects.all().delete()
    for _ in range(3):
        dispatch(recipient=auditor_user, kind="generic", title="x", message="y")

    client = authed_client(auditor_user)
    response = client.get("/api/notifications/unread-count/")
    assert response.status_code == 200
    assert response.json()["count"] == 3


def test_preferences_list_returns_merged_defaults(authed_client, auditor_user):
    """Even with no stored rows, the list returns one entry per kind."""
    NotificationPreference.objects.filter(user=auditor_user).delete()
    client = authed_client(auditor_user)
    response = client.get("/api/notification-preferences/")
    assert response.status_code == 200
    body = response.json()
    # One row per kind in the taxonomy
    assert len(body) == len(Notification.KIND_CHOICES)
    # The default for cap_assigned is in_app + email both on
    cap_pref = next(p for p in body if p["kind"] == Notification.KIND_CAP_ASSIGNED)
    assert cap_pref["inAppEnabled"] is True
    assert cap_pref["emailEnabled"] is True


def test_preferences_upsert(authed_client, auditor_user):
    client = authed_client(auditor_user)
    response = client.post(
        "/api/notification-preferences/",
        {"kind": Notification.KIND_CAP_ASSIGNED, "inAppEnabled": True, "emailEnabled": False},
        format="json",
    )
    assert response.status_code in (200, 201)
    pref = NotificationPreference.objects.get(user=auditor_user, kind=Notification.KIND_CAP_ASSIGNED)
    assert pref.in_app_enabled is True
    assert pref.email_enabled is False

    # Second POST upserts (same kind)
    response2 = client.post(
        "/api/notification-preferences/",
        {"kind": Notification.KIND_CAP_ASSIGNED, "inAppEnabled": False, "emailEnabled": False},
        format="json",
    )
    assert response2.status_code == 200
    pref.refresh_from_db()
    assert pref.in_app_enabled is False


# ══════════════════════════════════════════════════════════════════════
# dispatch_to_role helper
# ══════════════════════════════════════════════════════════════════════
def test_dispatch_to_role_notifies_every_user_with_role(audit_manager, roles):
    # audit_manager has the "Audit Manager" role from conftest fixtures
    Notification.objects.all().delete()
    rows = dispatch_to_role(
        role_name="Audit Manager",
        kind=Notification.KIND_GENERIC,
        title="Heads-up Managers",
        message="Read this",
    )
    assert len(rows) == 1
    assert rows[0].recipient == audit_manager
