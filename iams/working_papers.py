"""Working-paper service helpers — sign-off, versioning, search.

Mirrors the pattern of ``iams/workflows.py`` (approvals) and
``iams/notifications.py`` (notifications): a thin module that owns the
side-effecting verbs so the HTTP layer, admin, and Celery callers all
go through the same path.

Verbs:
  - ``sign_as_auditor(wp, by_user)``
  - ``sign_as_reviewer(wp, by_user)``    — also writes ``signed_off_at`` + locks
  - ``create_new_version(wp, **fields)`` — flips ``is_current_version`` on parent
  - ``populate_searchable_text(wp)``     — stub extraction for tests/dev
"""
from __future__ import annotations

import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from iams.models import WorkingPaper

logger = logging.getLogger(__name__)
User = get_user_model()


class SignOffError(Exception):
    """The sign-off attempt was refused by the workflow rules."""


# ──────────────────────────────────────────────────────────────────────
# Sign-off
# ──────────────────────────────────────────────────────────────────────
@transaction.atomic
def sign_as_auditor(wp: WorkingPaper, *, by_user: User) -> WorkingPaper:
    """Record the auditor signature.

    Refuses if:
      - the row is already finalized (both signatures present)
      - the same user has already signed as auditor
    Side effects:
      - ``auditor_signed_at = now``, ``auditor_signed_by = user``
      - status moves Draft → Under Review (only on first signature)
    """
    if wp.signed_off_at is not None:
        raise SignOffError("Working paper is already finalized.")
    if wp.auditor_signed_at is not None:
        raise SignOffError("Auditor has already signed this working paper.")
    if not by_user or not by_user.is_authenticated:
        raise SignOffError("Sign-off requires an authenticated user.")

    wp.auditor_signed_at = timezone.now()
    wp.auditor_signed_by = by_user
    if wp.status == WorkingPaper.STATUS_DRAFT:
        wp.status = WorkingPaper.STATUS_UNDER_REVIEW
    wp.save(update_fields=[
        "auditor_signed_at", "auditor_signed_by", "status", "updated_at",
    ])
    return wp


@transaction.atomic
def sign_as_reviewer(wp: WorkingPaper, *, by_user: User) -> WorkingPaper:
    """Record the reviewer signature and **lock the row**.

    Refuses if:
      - the row is already finalized
      - the auditor signature is missing (must sign auditor first)
      - reviewer is the same user as auditor (separation of duties)
    Side effects:
      - ``reviewer_signed_at = now``, ``reviewer_signed_by = user``
      - ``signed_off_at = now`` — this is what triggers the model's
        Python-level lock on subsequent ``.save()`` / ``.delete()``.
      - status → Signed
    """
    if wp.signed_off_at is not None:
        raise SignOffError("Working paper is already finalized.")
    if wp.auditor_signed_at is None:
        raise SignOffError("Auditor must sign before reviewer.")
    if not by_user or not by_user.is_authenticated:
        raise SignOffError("Sign-off requires an authenticated user.")
    if wp.auditor_signed_by_id == by_user.pk:
        raise SignOffError(
            "Reviewer must be a different user from the auditor "
            "(IIA 2330 separation of duties)."
        )

    now = timezone.now()
    wp.reviewer_signed_at = now
    wp.reviewer_signed_by = by_user
    wp.signed_off_at = now
    wp.status = WorkingPaper.STATUS_SIGNED
    # Use update_fields rather than .save() to flow through the save() guard;
    # the guard explicitly allows the same call (signed_off_at goes None→ts
    # in the same transaction so _state.adding is False but signed_off_at
    # was None at the start — the lock check sees the OLD value, not the new
    # one, so this works. Still, set _force_save_signed for safety.)
    wp._force_save_signed = True
    try:
        wp.save(update_fields=[
            "reviewer_signed_at", "reviewer_signed_by",
            "signed_off_at", "status", "updated_at",
        ])
    finally:
        wp._force_save_signed = False
    return wp


# ──────────────────────────────────────────────────────────────────────
# Versioning
# ──────────────────────────────────────────────────────────────────────
@transaction.atomic
def create_new_version(
    parent: WorkingPaper,
    *,
    file=None,
    title: str | None = None,
    description: str | None = None,
) -> WorkingPaper:
    """Create the next version of a working paper.

    The previous row's ``is_current_version`` flips to False and the new
    row inherits everything except: file (passed in), version (parent+1),
    parent (FK = old row), signatures (cleared), status (Draft), and the
    AV scan state (Pending — must rescan the new bytes).

    The (audit, reference, is_current_version) partial unique constraint
    enforces that only one row in the chain has ``is_current_version=True``,
    so this operation must run inside a transaction (Django ORM will queue
    the flip + insert in a single commit).
    """
    if parent.signed_off_at is None and parent.status not in (
        WorkingPaper.STATUS_SIGNED,
        WorkingPaper.STATUS_ARCHIVED,
    ):
        # Allow versioning of an unsigned-but-current row; just flip the flag.
        pass

    # Flip the parent off — bypass save() lock because we only touch
    # is_current_version (not signed_off_at).
    parent._force_save_signed = True
    try:
        parent.is_current_version = False
        parent.save(update_fields=["is_current_version", "updated_at"])
    finally:
        parent._force_save_signed = False

    new_wp = WorkingPaper.objects.create(
        audit=parent.audit,
        reference=parent.reference,
        title=title if title is not None else parent.title,
        description=description if description is not None else parent.description,
        file=file,
        file_type=parent.file_type if file is None else "",
        file_size_kb=parent.file_size_kb if file is None else 0,
        status=WorkingPaper.STATUS_DRAFT,
        parent=parent,
        version=parent.version + 1,
        is_current_version=True,
        # Signatures cleared on the new version
        auditor_signed_by=None, auditor_signed_at=None,
        reviewer_signed_by=None, reviewer_signed_at=None,
        signed_off_at=None,
        # Scan: pending again if a new file was uploaded, else inherit
        scan_status=(
            WorkingPaper.scan_status.field.default if file is not None else parent.scan_status
        ),
    )
    # Copy cross-references forward (a new version still concerns the same findings)
    new_wp.findings.set(parent.findings.all())
    return new_wp


# ──────────────────────────────────────────────────────────────────────
# Text extraction stub
# ──────────────────────────────────────────────────────────────────────
def populate_searchable_text(wp: WorkingPaper) -> str:
    """Build the ``searchable_text`` payload for a working paper.

    Production should run this via a Celery task that pulls bytes from
    MinIO and uses ``unstructured`` / ``pdfplumber`` / ``python-docx``
    to extract real document text. For Phase 3 Track 1 we use a stub
    that indexes the metadata fields plus, for plain-text files,
    inline content. Real extraction is a Phase 3 Track 1.1 follow-up.
    """
    parts: list[Any] = [wp.title, wp.description, wp.reference, wp.file_type]
    if wp.file and wp.file.name and wp.file.name.lower().endswith(".txt"):
        try:
            with wp.file.open("rb") as fh:
                # Cap at 1 MiB to keep memory predictable in tests
                content = fh.read(1024 * 1024).decode("utf-8", errors="ignore")
                parts.append(content)
        except Exception:  # noqa: BLE001
            logger.exception("populate_searchable_text: text read failed")
    text = "\n".join(p for p in parts if p).strip()
    return text
