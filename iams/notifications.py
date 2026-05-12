"""Central notification dispatch.

Anywhere in the codebase that wants to notify a user, calls
``iams.notifications.dispatch(...)``. The dispatcher:

  1. Resolves the recipient's preferences (with sane defaults for kinds
     they've never seen before).
  2. Creates a ``Notification`` row if ``in_app_enabled`` for that kind.
  3. Enqueues an email via the ``iams.tasks.notify.deliver_email`` Celery
     task if ``email_enabled`` for that kind. The task runs eagerly in
     tests and asynchronously in production.

The dispatcher is deliberately a single chokepoint — every other
notification site in the code (CAP-created signal, finding-raised signal,
approval workflow, beat tasks) should call ``dispatch`` rather than
constructing ``Notification`` rows by hand. This keeps preference
enforcement consistent and makes the audit trail traceable.

This module never raises into the caller. Notification failures are
logged at ERROR but do not bubble up — the underlying domain action
(e.g., "create CAP") must succeed even if notification breaks.
"""
from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.db.models import Model
from django.utils import timezone

from iams.models import Notification, NotificationPreference

logger = logging.getLogger(__name__)
User = get_user_model()


# ──────────────────────────────────────────────────────────────────────
# Default preferences per kind
#
# Convention: critical / personal events default ON for both channels;
# noisy / digest-style events default ON for in-app only; system-wide
# broadcasts default ON in-app, no email.
# ──────────────────────────────────────────────────────────────────────
DEFAULT_PREFS: dict[str, dict[str, bool]] = {
    Notification.KIND_AUDIT_ASSIGNED:     {"in_app": True,  "email": True},
    Notification.KIND_AUDIT_STATUS_CHANGE:{"in_app": True,  "email": False},
    Notification.KIND_FINDING_RAISED:     {"in_app": True,  "email": True},
    Notification.KIND_CAP_ASSIGNED:       {"in_app": True,  "email": True},
    Notification.KIND_CAP_DUE_SOON:       {"in_app": True,  "email": True},
    Notification.KIND_CAP_OVERDUE:        {"in_app": True,  "email": True},
    Notification.KIND_APPROVAL_REQUESTED: {"in_app": True,  "email": True},
    Notification.KIND_APPROVAL_APPROVED:  {"in_app": True,  "email": True},
    Notification.KIND_APPROVAL_REJECTED:  {"in_app": True,  "email": True},
    Notification.KIND_PASSWORD_RESET:     {"in_app": False, "email": True},
    Notification.KIND_FILE_QUARANTINE:    {"in_app": True,  "email": True},
    Notification.KIND_WEEKLY_DIGEST:      {"in_app": True,  "email": True},
    Notification.KIND_MFA_REMINDER:       {"in_app": True,  "email": True},
    Notification.KIND_GENERIC:            {"in_app": True,  "email": False},
}

# Email subject template per kind. ``{title}`` is substituted from the
# notification's ``title`` field at delivery time.
EMAIL_SUBJECTS: dict[str, str] = {
    Notification.KIND_AUDIT_ASSIGNED:     "[IAMS] You've been assigned to {title}",
    Notification.KIND_AUDIT_STATUS_CHANGE:"[IAMS] Audit status changed — {title}",
    Notification.KIND_FINDING_RAISED:     "[IAMS] New finding — {title}",
    Notification.KIND_CAP_ASSIGNED:       "[IAMS] You own a corrective action — {title}",
    Notification.KIND_CAP_DUE_SOON:       "[IAMS] CAP due in 3 days — {title}",
    Notification.KIND_CAP_OVERDUE:        "[IAMS] CAP OVERDUE — {title}",
    Notification.KIND_APPROVAL_REQUESTED: "[IAMS] Approval needed — {title}",
    Notification.KIND_APPROVAL_APPROVED:  "[IAMS] Your request was approved — {title}",
    Notification.KIND_APPROVAL_REJECTED:  "[IAMS] Your request was rejected — {title}",
    Notification.KIND_PASSWORD_RESET:     "[IAMS] Password reset",
    Notification.KIND_FILE_QUARANTINE:    "[IAMS] File quarantined by antivirus",
    Notification.KIND_WEEKLY_DIGEST:      "[IAMS] Weekly audit digest",
    Notification.KIND_MFA_REMINDER:       "[IAMS] Please set up multi-factor authentication",
    Notification.KIND_GENERIC:            "[IAMS] {title}",
}


def _resolve_preference(user: User, kind: str) -> dict[str, bool]:
    """Return ``{'in_app': bool, 'email': bool}`` for ``user``+``kind``.

    Falls back to ``DEFAULT_PREFS[kind]`` when the user has no explicit
    row for this kind.
    """
    default = DEFAULT_PREFS.get(kind, DEFAULT_PREFS[Notification.KIND_GENERIC])
    if user is None:
        return default
    pref = NotificationPreference.objects.filter(user=user, kind=kind).first()
    if pref is None:
        return default
    return {"in_app": pref.in_app_enabled, "email": pref.email_enabled}


def _build_target_fields(target: Model | None) -> dict[str, Any]:
    if target is None or not hasattr(target, "pk"):
        return {"target_content_type": None, "target_object_id": None}
    return {
        "target_content_type": ContentType.objects.get_for_model(target.__class__),
        "target_object_id": target.pk,
    }


def dispatch(
    *,
    recipient: User | None,
    kind: str,
    title: str,
    message: str,
    level: str = Notification.LEVEL_INFO,
    target: Model | None = None,
    link: str = "",
    module: str = "",
    email_context: dict[str, Any] | None = None,
) -> Notification | None:
    """Central notification dispatch.

    Args:
        recipient:     User to notify, or ``None`` for a system-wide broadcast
                       (broadcasts never email — there's no "everybody" inbox).
        kind:          One of the ``Notification.KIND_*`` constants.
        title:         Short headline shown in the bell and email subject.
        message:       Body — single paragraph, plain text.
        level:         Cosmetic urgency (info / warning / action).
        target:        Optional model instance the notification is about.
        link:          Optional FE deep-link (e.g. ``"/findings/F-001"``).
        module:        Optional module label for FE grouping.
        email_context: Extra template variables for the email.

    Returns the created ``Notification`` row, or ``None`` if both delivery
    channels were suppressed by preferences (rare — generally we always
    write the in-app row).
    """
    try:
        prefs = _resolve_preference(recipient, kind)

        # System-wide broadcast: write the row, never email (no recipient).
        is_broadcast = recipient is None
        wants_in_app = is_broadcast or prefs["in_app"]
        wants_email = (not is_broadcast) and prefs["email"]

        if not wants_in_app and not wants_email:
            logger.info(
                "notify: suppressed by prefs",
                extra={"kind": kind, "user_id": str(recipient.pk) if recipient else None},
            )
            return None

        notif: Notification | None = None
        if wants_in_app:
            notif = Notification.objects.create(
                recipient=recipient,
                kind=kind,
                title=title[:255],
                message=message,
                type=level,
                link=link[:512],
                module=module[:64],
                timestamp=timezone.now(),
                **_build_target_fields(target),
            )

        if wants_email:
            # Deferred import to dodge the celery → models circular cycle.
            from iams.tasks.notify import deliver_email
            deliver_email.delay(
                user_id=str(recipient.pk),
                kind=kind,
                title=title,
                message=message,
                link=link,
                notification_id=str(notif.id) if notif else None,
                extra_context=email_context or {},
            )

        return notif
    except Exception:  # noqa: BLE001
        logger.exception(
            "notify: dispatch failed",
            extra={"kind": kind, "user_id": str(recipient.pk) if recipient else None},
        )
        return None


def dispatch_to_role(
    *,
    role_name: str,
    kind: str,
    title: str,
    message: str,
    level: str = Notification.LEVEL_INFO,
    target: Model | None = None,
    link: str = "",
    module: str = "",
) -> list[Notification]:
    """Fan a notification out to every active user with a given role.

    Used by escalation flows (e.g. "remind every Audit Manager that
    approvals are stuck"). Returns the list of created ``Notification``
    rows (skipping suppressed-by-pref recipients).
    """
    from iams.models import UserProfile

    profiles = (
        UserProfile.objects
        .filter(role__name=role_name, status="Active")
        .select_related("user")
    )
    rows: list[Notification] = []
    for profile in profiles:
        notif = dispatch(
            recipient=profile.user,
            kind=kind,
            title=title,
            message=message,
            level=level,
            target=target,
            link=link,
            module=module,
        )
        if notif is not None:
            rows.append(notif)
    return rows
