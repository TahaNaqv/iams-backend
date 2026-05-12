"""Celery application entry point.

Used by ``celery -A config worker`` and ``celery -A config beat``.
"""
from __future__ import annotations

import os

from celery import Celery

# The settings module is overridden via env when running in different
# environments. Dev module is a safe default for local invocation.
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("iams")

# Pulls config from Django settings, looking for keys prefixed with CELERY_
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-discovers @shared_task in every installed app
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self) -> None:  # pragma: no cover
    """Sanity-check task — log own request payload."""
    print(f"Request: {self.request!r}")
