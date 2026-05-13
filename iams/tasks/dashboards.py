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
    """Drop dashboard cache keys + sync live-state Prometheus gauges.

    The cache invalidation lets the next FE poll repopulate keys with
    current data. The gauge refresh keeps ``iams_caps_overdue_current``
    and ``iams_approvals_pending_current`` accurate even if some
    individual signals were missed (process restart, lost message).
    """
    from iams.dashboards import invalidate_dashboard_cache
    from iams.metrics import refresh_business_gauges

    removed = invalidate_dashboard_cache()
    gauges = refresh_business_gauges()
    logger.info(
        "dashboards: invalidated %s cache key(s); gauges %s",
        removed, gauges,
    )
    return {"invalidated": removed, "gauges": gauges}
