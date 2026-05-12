"""IAMS Celery tasks package.

Tasks are auto-discovered by Celery via ``app.autodiscover_tasks()`` in
``config/celery.py``. They live here organized by domain:

    iams.tasks.auth        — password reset, MFA reminder emails
    iams.tasks.notify      — in-app + email notification dispatch (Phase 2)
    iams.tasks.reports     — async PDF/Excel report generation (Phase 4)
    iams.tasks.scans       — ClamAV virus scanning of uploads (Phase 1 Track 3)
    iams.tasks.cleanup     — scheduled retention/archival jobs (Phase 2/5)
"""
from .auth import send_password_reset_email
from .notify import (
    deliver_email,
    dispatch_cap_overdue_reminders,
    dispatch_weekly_digest,
)
from .scans import scan_uploaded_file

__all__ = [
    "send_password_reset_email",
    "scan_uploaded_file",
    "deliver_email",
    "dispatch_cap_overdue_reminders",
    "dispatch_weekly_digest",
]
