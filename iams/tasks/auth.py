"""Auth-related async tasks.

Password reset is the canonical asynchronous email: we must never block
the request thread on SMTP since it may be slow, flaky, or temporarily
unreachable on an on-prem network.
"""
from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    name="iams.send_password_reset_email",
)
def send_password_reset_email(self, user_id: str, frontend_base_url: str) -> dict:
    """Send a password-reset email with a tokenized confirm link.

    The link is built from ``frontend_base_url`` (provided by the caller so
    we don't bake any URL into the backend) plus the encoded user id and
    a signed token from Django's ``default_token_generator``. The token
    expires after ``PASSWORD_RESET_TIMEOUT`` (Django default: 3 days).

    Always returns successfully even if the user does not exist or has
    no email — this prevents email-enumeration via response timing.
    """
    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id, is_active=True)
    except User.DoesNotExist:
        logger.info(
            "password_reset_email: user not found or inactive",
            extra={"user_id": user_id},
        )
        return {"sent": False, "reason": "user_not_found"}

    if not user.email:
        logger.info("password_reset_email: user has no email", extra={"user_id": user_id})
        return {"sent": False, "reason": "no_email"}

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    base = frontend_base_url.rstrip("/")
    reset_url = f"{base}/reset-password/{uid}/{token}"

    context = {
        "user": user,
        "user_email": user.email,
        "user_name": (user.first_name or user.email).strip(),
        "reset_url": reset_url,
        "site_name": "IAMS",
        "expiry_hours": getattr(settings, "PASSWORD_RESET_TIMEOUT", 259200) // 3600,
    }

    subject = "Reset your IAMS password"
    text_body = render_to_string("iams/email/password_reset.txt", context)
    html_body = render_to_string("iams/email/password_reset.html", context)

    msg = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    msg.attach_alternative(html_body, "text/html")
    msg.send()

    logger.info(
        "password_reset_email: sent",
        extra={"user_id": str(user.pk), "email": user.email},
    )
    return {"sent": True, "email": user.email}
