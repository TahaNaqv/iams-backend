"""Config package — ensures the Celery app is loaded with Django."""
from __future__ import annotations

from .celery import app as celery_app

__all__ = ("celery_app",)
