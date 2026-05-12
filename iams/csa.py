"""Control Self-Assessment service helpers.

Scoring + submit + challenge verbs, isolated from the HTTP layer so the
same code path is reachable from the API, admin actions, and future
bulk-import jobs.

Scoring rule (FR-CSA-03): for each question, the answer earns
``weight`` points scaled by how well it scored:

  - yes_no            "yes" → 1.0, anything else → 0.0
  - scale_1_5         1..5 → (n-1)/4  → 0%, 25%, 50%, 75%, 100%
  - text              non-empty → 1.0, empty → 0.0
  - evidence_required non-empty value AND non-null evidence_file → 1.0,
                      else 0.0

The overall score is sum(earned) / sum(weight) * 100, capped 0..100.
Per-category scores (design / operating) are computed the same way over
the subset of questions in that category.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Iterable

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from iams.models import CSAAnswer, CSAQuestion, CSAResponse

logger = logging.getLogger(__name__)
User = get_user_model()


class CSAError(Exception):
    """Domain error from the CSA workflow."""


# ──────────────────────────────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────────────────────────────
def _answer_score_fraction(answer: CSAAnswer) -> float:
    """Return 0.0..1.0 representing how much of the question's weight
    this answer earns."""
    q = answer.question
    v = (answer.value or "").strip()

    if q.response_type == CSAQuestion.TYPE_YES_NO:
        return 1.0 if v.lower() in ("yes", "y", "true", "1") else 0.0

    if q.response_type == CSAQuestion.TYPE_SCALE_1_5:
        try:
            n = int(v)
        except (TypeError, ValueError):
            return 0.0
        if n < 1 or n > 5:
            return 0.0
        return (n - 1) / 4.0

    if q.response_type == CSAQuestion.TYPE_TEXT:
        return 1.0 if v else 0.0

    if q.response_type == CSAQuestion.TYPE_EVIDENCE_REQUIRED:
        return 1.0 if (v and answer.evidence_file_id is not None) else 0.0

    return 0.0


def _score_for_questions(answers_by_qid: dict, questions: Iterable[CSAQuestion]) -> Decimal:
    """Compute a 0..100 score over the given subset of questions."""
    earned = 0.0
    total_weight = 0
    for q in questions:
        ans = answers_by_qid.get(q.pk)
        weight = max(1, int(q.weight))
        total_weight += weight
        if ans is not None:
            earned += _answer_score_fraction(ans) * weight
    if total_weight == 0:
        return Decimal("0.00")
    pct = (earned / total_weight) * 100.0
    return Decimal(f"{pct:.2f}")


def compute_scores(response: CSAResponse) -> dict[str, Decimal | None]:
    """Compute overall + per-category scores for a response.

    Returns ``{"overall": Decimal, "design": Decimal|None, "operating": Decimal|None}``.
    ``design`` and ``operating`` are ``None`` when there are no
    questions in that category.
    """
    answers_by_qid = {a.question_id: a for a in response.answers.select_related("question").all()}
    questions = list(response.questionnaire.questions.all())

    overall = _score_for_questions(answers_by_qid, questions)
    design_q = [q for q in questions if q.category == CSAQuestion.CATEGORY_DESIGN]
    operating_q = [q for q in questions if q.category == CSAQuestion.CATEGORY_OPERATING]
    design = _score_for_questions(answers_by_qid, design_q) if design_q else None
    operating = _score_for_questions(answers_by_qid, operating_q) if operating_q else None

    return {"overall": overall, "design": design, "operating": operating}


# ──────────────────────────────────────────────────────────────────────
# Submit
# ──────────────────────────────────────────────────────────────────────
@transaction.atomic
def submit_response(response: CSAResponse, *, by_user: User) -> CSAResponse:
    """Lock the response, compute scores, fire weak-control side effects.

    Refuses if:
      - already submitted / under review / closed
      - the questionnaire is not Active
      - the response has zero answers (nothing to score)
    Side effects:
      - status → submitted
      - submitted_at = now
      - score_overall / score_design / score_operating populated
      - is_weak = True if score < questionnaire.weak_threshold
      - If weak: dispatch CSA_WEAK_CONTROL notification to Audit Managers
        + (best-effort) bump the auditable entity's risk_rating to High
        so the Phase 4 risk engine picks it up.
    """
    if not by_user or not by_user.is_authenticated:
        raise CSAError("Submit requires an authenticated user.")
    if response.status != CSAResponse.STATUS_DRAFT:
        raise CSAError(
            f"Cannot submit: response is '{response.status}', expected 'draft'."
        )
    if response.questionnaire.status != "active":
        raise CSAError(
            f"Cannot submit against a '{response.questionnaire.status}' questionnaire."
        )
    if not response.answers.exists():
        raise CSAError("Cannot submit an empty response.")

    scores = compute_scores(response)
    response.score_overall = scores["overall"]
    response.score_design = scores["design"]
    response.score_operating = scores["operating"]
    response.is_weak = scores["overall"] < response.questionnaire.weak_threshold
    response.status = CSAResponse.STATUS_SUBMITTED
    response.submitted_at = timezone.now()
    response.responder = response.responder or by_user
    response.save(update_fields=[
        "score_overall", "score_design", "score_operating",
        "is_weak", "status", "submitted_at", "responder", "updated_at",
    ])

    if response.is_weak:
        _fire_weak_control_signals(response)

    return response


def _fire_weak_control_signals(response: CSAResponse) -> None:
    """Best-effort: notify Audit Managers + flag the entity.

    Wrapped in try/except so a notification failure doesn't roll back
    the submit. The flag is captured even when notifications fail.
    """
    try:
        from iams.notifications import Notification, dispatch_to_role
        ref_label = response.entity.name if response.entity_id else (response.department or "—")
        score_str = f"{response.score_overall}"
        dispatch_to_role(
            role_name="Audit Manager",
            kind=Notification.KIND_GENERIC,
            title=f"CSA weak control — {ref_label}",
            message=(
                f"Score {score_str}/100 on '{response.questionnaire.title}' is below the "
                f"weak-control threshold ({response.questionnaire.weak_threshold}). "
                "Consider prioritising this unit in the next audit plan."
            ),
            level=Notification.LEVEL_WARNING,
            target=response,
            link="/csa",
            module="CSA",
        )
    except Exception:  # noqa: BLE001
        logger.exception("csa: weak-control notification dispatch failed")

    try:
        if response.entity_id:
            entity = response.entity
            if entity.risk_rating != "Critical":
                entity.risk_rating = "High"
                entity.save(update_fields=["risk_rating", "updated_at"])
    except Exception:  # noqa: BLE001
        logger.exception("csa: entity risk_rating bump failed")


# ──────────────────────────────────────────────────────────────────────
# Challenge workflow
# ──────────────────────────────────────────────────────────────────────
@transaction.atomic
def open_challenge(answer: CSAAnswer, *, by_user: User, note: str) -> CSAAnswer:
    """Auditor opens a challenge on a specific answer.

    Refuses if the parent response is still a draft or already closed.
    Side effects:
      - answer.challenge_status = open
      - response.status → under_review
    """
    if not by_user or not by_user.is_authenticated:
        raise CSAError("Challenge requires an authenticated user.")
    if not note or not note.strip():
        raise CSAError("Challenge note is required.")
    parent = answer.response
    if parent.status == CSAResponse.STATUS_DRAFT:
        raise CSAError("Cannot challenge a draft response — wait for submit.")
    if parent.status == CSAResponse.STATUS_CLOSED:
        raise CSAError("Response is closed; reopen before challenging.")

    answer.challenge_status = CSAAnswer.CHALLENGE_OPEN
    answer.challenge_note = note.strip()
    answer.challenged_by = by_user
    answer.challenged_at = timezone.now()
    answer.save(update_fields=[
        "challenge_status", "challenge_note", "challenged_by",
        "challenged_at", "updated_at",
    ])

    if parent.status != CSAResponse.STATUS_UNDER_REVIEW:
        parent.status = CSAResponse.STATUS_UNDER_REVIEW
        parent.save(update_fields=["status", "updated_at"])

    return answer


@transaction.atomic
def resolve_challenge(answer: CSAAnswer, *, by_user: User, note: str = "") -> CSAAnswer:
    """Auditor (or responder) marks a challenge resolved."""
    if not by_user or not by_user.is_authenticated:
        raise CSAError("Resolve requires an authenticated user.")
    if answer.challenge_status != CSAAnswer.CHALLENGE_OPEN:
        raise CSAError("No open challenge on this answer.")

    answer.challenge_status = CSAAnswer.CHALLENGE_RESOLVED
    answer.resolution_note = note.strip()
    answer.resolved_by = by_user
    answer.resolved_at = timezone.now()
    answer.save(update_fields=[
        "challenge_status", "resolution_note", "resolved_by",
        "resolved_at", "updated_at",
    ])

    # If no open challenges remain on the response, move it back to
    # submitted (the auditor can still re-challenge or close).
    parent = answer.response
    still_open = parent.answers.filter(challenge_status=CSAAnswer.CHALLENGE_OPEN).exists()
    if not still_open and parent.status == CSAResponse.STATUS_UNDER_REVIEW:
        parent.status = CSAResponse.STATUS_SUBMITTED
        parent.save(update_fields=["status", "updated_at"])

    return answer


@transaction.atomic
def close_response(response: CSAResponse, *, by_user: User) -> CSAResponse:
    """Auditor closes the review."""
    if response.status == CSAResponse.STATUS_DRAFT:
        raise CSAError("Cannot close a draft response.")
    if response.answers.filter(challenge_status=CSAAnswer.CHALLENGE_OPEN).exists():
        raise CSAError("Cannot close while challenges remain open.")
    response.status = CSAResponse.STATUS_CLOSED
    response.closed_at = timezone.now()
    response.save(update_fields=["status", "closed_at", "updated_at"])
    return response
