"""Antivirus scanning of user-uploaded files.

Architecture:

  1. The upload view (``EvidenceByAuditView.post`` /
     ``ManagedDocumentViewSet.create``) persists the new row with
     ``scan_status='pending'`` and dispatches ``scan_uploaded_file.delay(...)``.
  2. This task opens the file (works for both local FileSystemStorage and
     MinIO/S3-backed storage), streams it to a ``clamd`` instance over TCP
     using ``INSTREAM``, and writes the result back to the row:
       - clean    → ``scan_status='clean'``, ``scanned_at=now``
       - infected → ``scan_status='infected'``, ``quarantined=True``,
                    ``scan_signature=<virus name>``, file becomes
                    unavailable for download
       - error    → ``scan_status='error'``, ``quarantined=True``
                    (fail-closed: humans must review)
  3. Download endpoints check ``quarantined`` and refuse to issue a signed
     URL for quarantined rows.

The clamd daemon is a separate container; configuration:

  CLAMD_HOST            default 'clamav'
  CLAMD_PORT            default 3310
  CLAMD_SCAN_TIMEOUT    default 60 (seconds)
  CLAMD_MAX_FILE_MB     default 100 (skip + flag larger files)

In dev without a clamd container, set ``CLAMD_SKIP=1`` to short-circuit the
scan to "clean" (test settings already do this implicitly via eager Celery
+ env vars). In tests, ``conftest`` patches the clamd client directly.
"""
from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from iams.models import EvidenceFile, ManagedDocument, WorkingPaper

logger = logging.getLogger(__name__)


# Map ``model_label`` string → Django model class. Avoids passing model
# instances through Celery (which can't pickle querysets safely across
# worker restarts) and keeps task signatures JSON-serializable.
_SCANNABLE_MODELS = {
    "EvidenceFile": EvidenceFile,
    "ManagedDocument": ManagedDocument,
    "WorkingPaper": WorkingPaper,
}


def _get_clamd_client():  # pragma: no cover — exercised via mocking
    """Build a ``clamd`` TCP client from settings.

    Imported lazily so the rest of the app doesn't pay the import cost on
    every cold start, and so tests can patch this function rather than the
    library module.
    """
    import clamd  # noqa: PLC0415 — intentional lazy import

    host = getattr(settings, "CLAMD_HOST", "clamav")
    port = int(getattr(settings, "CLAMD_PORT", 3310))
    timeout = int(getattr(settings, "CLAMD_SCAN_TIMEOUT", 60))
    return clamd.ClamdNetworkSocket(host=host, port=port, timeout=timeout)


def _interpret_instream_result(result: Any) -> tuple[str, str]:
    """Map clamd's INSTREAM response into ``(status, signature)``.

    clamd returns ``{"stream": ("OK", None)}`` for clean files and
    ``{"stream": ("FOUND", "<virus name>")}`` for infected ones. ERROR
    yields ``("ERROR", "<message>")``.
    """
    if not isinstance(result, dict) or "stream" not in result:
        return EvidenceFile.SCAN_ERROR, "unexpected_clamd_response"
    verdict, detail = result["stream"]
    if verdict == "OK":
        return EvidenceFile.SCAN_CLEAN, ""
    if verdict == "FOUND":
        return EvidenceFile.SCAN_INFECTED, detail or "unknown_signature"
    return EvidenceFile.SCAN_ERROR, detail or verdict


@shared_task(
    bind=True,
    name="iams.scan_uploaded_file",
    max_retries=3,
    default_retry_delay=30,
    autoretry_for=(ConnectionError, OSError),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
)
def scan_uploaded_file(self, model_label: str, object_id: str) -> dict:
    """Scan an uploaded file's bytes through clamd.

    Args:
        model_label: ``"EvidenceFile"`` or ``"ManagedDocument"``.
        object_id:   primary key (UUID string).

    Returns a dict summary for telemetry — never raises on virus detection
    (that's a normal outcome, recorded on the row).
    """
    model = _SCANNABLE_MODELS.get(model_label)
    if model is None:
        logger.error("scan: unknown model_label %r", model_label)
        return {"scanned": False, "reason": "unknown_model_label"}

    try:
        instance = model.objects.get(pk=object_id)
    except model.DoesNotExist:
        logger.info(
            "scan: row gone before scan completed (deleted?)",
            extra={"model": model_label, "object_id": object_id},
        )
        return {"scanned": False, "reason": "row_missing"}

    file_field = instance.file
    if not file_field:
        logger.info(
            "scan: row has no file attached, skipping",
            extra={"model": model_label, "object_id": object_id},
        )
        instance.scan_status = EvidenceFile.SCAN_CLEAN
        instance.scanned_at = timezone.now()
        instance.save(update_fields=["scan_status", "scanned_at"])
        return {"scanned": False, "reason": "no_file"}

    if getattr(settings, "CLAMD_SKIP", False):
        logger.warning(
            "scan: CLAMD_SKIP enabled — marking clean without scanning",
            extra={"model": model_label, "object_id": object_id},
        )
        instance.scan_status = EvidenceFile.SCAN_CLEAN
        instance.scanned_at = timezone.now()
        instance.save(update_fields=["scan_status", "scanned_at"])
        return {"scanned": False, "reason": "clamd_skip"}

    max_mb = int(getattr(settings, "CLAMD_MAX_FILE_MB", 100))
    if file_field.size > max_mb * 1024 * 1024:
        logger.warning(
            "scan: file exceeds CLAMD_MAX_FILE_MB — quarantining",
            extra={"model": model_label, "object_id": object_id, "size": file_field.size},
        )
        instance.scan_status = EvidenceFile.SCAN_ERROR
        instance.scan_signature = "file_too_large"
        instance.quarantined = True
        instance.scanned_at = timezone.now()
        instance.save(
            update_fields=["scan_status", "scan_signature", "quarantined", "scanned_at"]
        )
        return {"scanned": False, "reason": "too_large"}

    # Stream the file through clamd INSTREAM. We open in binary mode and
    # let clamd library chunk it — works identically for local disk and
    # MinIO/S3 storage backends.
    client = _get_clamd_client()
    try:
        with file_field.open("rb") as fh:
            result = client.instream(fh)
    except Exception as exc:  # noqa: BLE001 — Celery autoretry handles network errors
        logger.exception(
            "scan: clamd error",
            extra={"model": model_label, "object_id": object_id},
        )
        instance.scan_status = EvidenceFile.SCAN_ERROR
        instance.scan_signature = type(exc).__name__
        instance.quarantined = True  # fail-closed
        instance.scanned_at = timezone.now()
        instance.save(
            update_fields=["scan_status", "scan_signature", "quarantined", "scanned_at"]
        )
        # Re-raise non-retryable errors so they reach Sentry; ConnectionError
        # is in autoretry_for so Celery will retry that path automatically.
        if isinstance(exc, (ConnectionError, OSError)):
            raise
        return {"scanned": False, "reason": "clamd_error", "error": str(exc)}

    status, signature = _interpret_instream_result(result)
    instance.scan_status = status
    instance.scan_signature = signature
    instance.quarantined = status != EvidenceFile.SCAN_CLEAN
    instance.scanned_at = timezone.now()
    instance.save(
        update_fields=["scan_status", "scan_signature", "quarantined", "scanned_at"]
    )

    if status == EvidenceFile.SCAN_INFECTED:
        logger.warning(
            "scan: INFECTED — %s",
            signature,
            extra={"model": model_label, "object_id": object_id},
        )
        # Record the quarantine as a first-class audit event so it shows up
        # in the AuditLog page next to the upload event itself.
        from iams.audit import record_audit_event  # local to avoid import cycles
        record_audit_event(
            action="file_quarantine",
            actor="system:clamav",
            target=instance,
            details={"signature": signature, "model": model_label},
        )

    return {
        "scanned": True,
        "status": status,
        "signature": signature,
        "object_id": str(object_id),
    }
