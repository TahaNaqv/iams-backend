"""Email delivery for notifications + scheduled beat tasks.

`deliver_email` is the worker side of `iams.notifications.dispatch`: it
runs asynchronously, sends a templated email via Django's email backend
(SMTP / Postfix relay / mailhog), and marks the originating ``Notification``
row as delivered.

`dispatch_cap_overdue_reminders` and `dispatch_weekly_digest` are the
Celery beat tasks scheduled in ``config/celery_schedule.py``.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)
User = get_user_model()


def _frontend_base() -> str:
    return getattr(settings, "FRONTEND_BASE_URL", "") or (
        settings.CORS_ALLOWED_ORIGINS[0] if settings.CORS_ALLOWED_ORIGINS else "http://localhost:5173"
    ).rstrip("/")


# ──────────────────────────────────────────────────────────────────────
# Per-event email delivery
# ──────────────────────────────────────────────────────────────────────
@shared_task(
    bind=True,
    name="iams.notify.deliver_email",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def deliver_email(
    self,
    *,
    user_id: str,
    kind: str,
    title: str,
    message: str,
    link: str = "",
    notification_id: str | None = None,
    extra_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send a notification email and mark the in-app row as delivered."""
    from iams.models import Notification
    from iams.notifications import EMAIL_SUBJECTS

    try:
        user = User.objects.get(pk=user_id, is_active=True)
    except User.DoesNotExist:
        logger.info("notify.email: user missing/inactive", extra={"user_id": user_id})
        return {"sent": False, "reason": "user_missing"}

    if not user.email:
        logger.info("notify.email: user has no email", extra={"user_id": user_id})
        return {"sent": False, "reason": "no_email"}

    subject_template = EMAIL_SUBJECTS.get(kind, "[IAMS] {title}")
    subject = subject_template.format(title=title)
    frontend_base = _frontend_base().rstrip("/")
    full_link = f"{frontend_base}{link}" if link.startswith("/") else (link or frontend_base)

    context = {
        "user_name": (user.first_name or user.email).strip(),
        "user_email": user.email,
        "title": title,
        "message": message,
        "link": full_link,
        "kind": kind,
        "site_name": "IAMS",
        **(extra_context or {}),
    }

    text_body = render_to_string("iams/email/notification.txt", context)
    html_body = render_to_string("iams/email/notification.html", context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()

    if notification_id:
        try:
            Notification.objects.filter(pk=notification_id).update(
                email_sent_at=timezone.now()
            )
        except Exception:  # noqa: BLE001 — never let a status update kill the task
            logger.exception("notify.email: marking row delivered failed")

    return {"sent": True, "user_id": user_id, "kind": kind}


# ──────────────────────────────────────────────────────────────────────
# Scheduled: nightly CAP-overdue scan
# ──────────────────────────────────────────────────────────────────────
@shared_task(name="iams.notify.cap_overdue_scan")
def dispatch_cap_overdue_reminders() -> dict[str, int]:
    """Find CAPs that are overdue or about to be, and notify owners.

    Runs nightly. The same CAP isn't spammed every night — we only fire
    if no overdue-reminder notification for that CAP has been issued in
    the last 24 hours.
    """
    from iams.models import CorrectiveAction, Notification, UserProfile
    from iams.notifications import dispatch

    today = timezone.now().date()
    three_days = today + timedelta(days=3)
    twenty_four_h_ago = timezone.now() - timedelta(hours=24)

    overdue_qs = CorrectiveAction.objects.exclude(status="Closed").filter(
        due_date__lt=today
    )
    due_soon_qs = (
        CorrectiveAction.objects.exclude(status="Closed")
        .filter(due_date__gte=today, due_date__lte=three_days)
    )

    overdue_count = 0
    due_soon_count = 0

    for cap in overdue_qs:
        owner = _resolve_user_from_owner_label(cap.owner)
        if owner is None:
            continue
        # Skip if we already reminded in the last 24h
        if Notification.objects.filter(
            recipient=owner,
            kind=Notification.KIND_CAP_OVERDUE,
            target_object_id=cap.pk,
            timestamp__gte=twenty_four_h_ago,
        ).exists():
            continue
        days_late = (today - cap.due_date).days
        dispatch(
            recipient=owner,
            kind=Notification.KIND_CAP_OVERDUE,
            title=f"CAP overdue: {cap.title}",
            message=f"This corrective action was due {days_late} day(s) ago.",
            level=Notification.LEVEL_WARNING,
            target=cap,
            link=f"/cap/{cap.pk}",
            module="CAPs",
        )
        overdue_count += 1

    for cap in due_soon_qs:
        owner = _resolve_user_from_owner_label(cap.owner)
        if owner is None:
            continue
        if Notification.objects.filter(
            recipient=owner,
            kind=Notification.KIND_CAP_DUE_SOON,
            target_object_id=cap.pk,
            timestamp__gte=twenty_four_h_ago,
        ).exists():
            continue
        days_until = (cap.due_date - today).days
        dispatch(
            recipient=owner,
            kind=Notification.KIND_CAP_DUE_SOON,
            title=f"CAP due in {days_until} day(s): {cap.title}",
            message=f"Due on {cap.due_date.isoformat()}.",
            level=Notification.LEVEL_INFO,
            target=cap,
            link=f"/cap/{cap.pk}",
            module="CAPs",
        )
        due_soon_count += 1

    logger.info(
        "notify.cap_overdue_scan: dispatched",
        extra={"overdue": overdue_count, "due_soon": due_soon_count},
    )
    return {"overdue": overdue_count, "due_soon": due_soon_count}


# ──────────────────────────────────────────────────────────────────────
# Scheduled: weekly digest (Mondays 08:00 local)
# ──────────────────────────────────────────────────────────────────────
@shared_task(name="iams.notify.weekly_digest")
def dispatch_weekly_digest() -> dict[str, int]:
    """Send each active user a one-shot weekly summary of their workload."""
    from iams.models import (
        Audit, CorrectiveAction, Finding, Notification, UserProfile,
    )
    from iams.notifications import dispatch

    week_start = timezone.now() - timedelta(days=7)
    sent = 0

    # Aggregate org-wide stats once; the per-user summary slices them.
    org_findings_new = Finding.objects.filter(created_date__gte=week_start.date()).count()
    org_caps_overdue = CorrectiveAction.objects.exclude(status="Closed").filter(
        due_date__lt=timezone.now().date()
    ).count()
    org_audits_in_progress = Audit.objects.filter(status="In Progress").count()

    for profile in UserProfile.objects.filter(status="Active").select_related("user"):
        user = profile.user
        if not user.email or not user.is_active:
            continue

        my_caps = CorrectiveAction.objects.filter(owner=user.email).exclude(status="Closed")
        my_overdue = my_caps.filter(due_date__lt=timezone.now().date()).count()
        my_open = my_caps.count()

        dispatch(
            recipient=user,
            kind=Notification.KIND_WEEKLY_DIGEST,
            title="Your weekly IAMS digest",
            message=(
                f"You have {my_open} open corrective action(s) — {my_overdue} overdue. "
                f"Organization-wide this week: {org_findings_new} new findings, "
                f"{org_caps_overdue} CAPs overdue, {org_audits_in_progress} audits in progress."
            ),
            level=Notification.LEVEL_INFO,
            link="/",
            module="System",
            email_context={
                "my_open_caps": my_open,
                "my_overdue_caps": my_overdue,
                "org_findings_new": org_findings_new,
                "org_caps_overdue": org_caps_overdue,
                "org_audits_in_progress": org_audits_in_progress,
            },
        )
        sent += 1

    logger.info("notify.weekly_digest: dispatched %s digests", sent)
    return {"sent": sent}


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────
def _resolve_user_from_owner_label(owner_label: str) -> User | None:
    """Best-effort resolve a CAP/Finding ``owner`` string to a User.

    Owner is stored as a free-text string (legacy compatibility) but we
    can usually match it to a real user by email, username, or display
    name. Returns ``None`` if no match — caller skips notification.
    """
    if not owner_label:
        return None
    label = owner_label.strip()
    # Exact email match (most common; what the CAP serializer writes)
    user = User.objects.filter(email__iexact=label).first()
    if user:
        return user
    user = User.objects.filter(username__iexact=label).first()
    if user:
        return user
    # Last shot: "First Last" match
    if " " in label:
        first, last = label.split(" ", 1)
        user = User.objects.filter(first_name__iexact=first, last_name__iexact=last).first()
        if user:
            return user
    return None
