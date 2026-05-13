"""Scheduled dashboard maintenance.

Drops the dashboard cache every 5 minutes (the beat cadence — see
``CELERY_BEAT_SCHEDULE``). This is the simplest "freshness" strategy:
let the next poll repopulate the keys with current data instead of
fighting cache-invalidation races on every domain write.

Phase 5 hardening will replace this with Postgres materialized views
refreshed by their own beat task, and per-key invalidation on write
events. For now: simple, debuggable, correct.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="iams.dashboards.refresh_caches")
def refresh_dashboard_caches() -> dict:
    """Drop all dashboard cache keys so the next request fetches fresh."""
    from iams.dashboards import invalidate_dashboard_cache

    removed = invalidate_dashboard_cache()
    logger.info("dashboards: invalidated %s cache key(s)", removed)
    return {"invalidated": removed}
