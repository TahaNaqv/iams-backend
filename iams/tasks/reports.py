"""Async report generation.

The FE kicks off a job via ``POST /api/reports/generate/`` → creates a
``ReportJob`` row in ``pending``. The view enqueues this task; Celery
picks it up, dispatches to the right renderer via the
``iams.reports.RENDERERS`` registry, and the renderer writes the output
into ``ReportJob.output_file``. When done, the user gets a
notification with a deep-link.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="iams.reports.generate_report")
def generate_report(job_id: str) -> dict:
    """Run the renderer for a ``ReportJob`` and notify the requester."""
    from iams.models import Notification, ReportJob
    from iams.notifications import dispatch
    from iams.reports import RENDERERS

    try:
        job = ReportJob.objects.get(pk=job_id)
    except ReportJob.DoesNotExist:
        logger.info("reports: job %s vanished before render", job_id)
        return {"rendered": False, "reason": "missing"}

    try:
        from iams.metrics import report_jobs_total
        report_jobs_total.labels(kind=job.kind or "unknown").inc()
    except Exception:  # noqa: BLE001
        logger.exception("metrics: failed to bump report_jobs_total")

    renderer_cls = RENDERERS.get(job.kind)
    if renderer_cls is None:
        job.status = ReportJob.STATUS_FAILED
        job.error = f"No renderer registered for kind '{job.kind}'."
        job.save(update_fields=["status", "error", "updated_at"])
        try:
            from iams.metrics import report_jobs_failed_total
            report_jobs_failed_total.labels(kind=job.kind or "unknown").inc()
        except Exception:  # noqa: BLE001
            logger.exception("metrics: failed to bump report_jobs_failed_total")
        return {"rendered": False, "reason": "no_renderer"}

    renderer = renderer_cls()
    job = renderer.run(job)
    try:
        from iams.metrics import report_jobs_completed_total, report_jobs_failed_total
        if job.status == ReportJob.STATUS_COMPLETED:
            report_jobs_completed_total.labels(kind=job.kind or "unknown").inc()
        elif job.status == ReportJob.STATUS_FAILED:
            report_jobs_failed_total.labels(kind=job.kind or "unknown").inc()
    except Exception:  # noqa: BLE001
        logger.exception("metrics: failed to bump report-job lifecycle counter")

    # Notify the requester
    if job.requested_by_id:
        if job.status == ReportJob.STATUS_COMPLETED:
            dispatch(
                recipient=job.requested_by,
                kind=Notification.KIND_GENERIC,
                title=f"Report ready: {job.title or job.get_kind_display()}",
                message=f"Your '{job.get_kind_display()}' is ready to download.",
                level=Notification.LEVEL_INFO,
                target=job,
                link=f"/reports/{job.pk}",
                module="Reports",
            )
        else:
            dispatch(
                recipient=job.requested_by,
                kind=Notification.KIND_GENERIC,
                title=f"Report failed: {job.title or job.get_kind_display()}",
                message=(job.error or "Generation failed.")[:300],
                level=Notification.LEVEL_WARNING,
                target=job,
                link=f"/reports/{job.pk}",
                module="Reports",
            )

    return {
        "rendered": job.status == ReportJob.STATUS_COMPLETED,
        "status": job.status,
        "job_id": str(job.pk),
    }
