"""Async risk-score recompute for the Audit Universe.

The ``POST /api/auditable-entities/recompute-risk-scores/`` action snapshots
every entity scored against the active ``RiskScoringModel``. On a large
universe that is an O(n) walk (each row re-scored) plus a rank rebuild — far
too heavy to run synchronously on the request thread, where it would tie up a
worker and risk a gateway timeout. This task moves the work onto a Celery
worker; the action returns ``202 Accepted`` immediately.

Runs eagerly (inline) under the test settings' ``CELERY_TASK_ALWAYS_EAGER``.
"""
from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="iams.audit_universe.recompute_risk_scores")
def recompute_active_model_scores(user_id: str | None = None) -> dict:
    """Re-snapshot every entity scored against the active model.

    Returns a small summary dict (also becomes the Celery result). No-ops
    cleanly when no active model is configured.
    """
    from django.contrib.auth import get_user_model

    from iams.models import RiskScoringModel
    from iams.risk_engine import recompute_all_scores_for_model

    model = RiskScoringModel.objects.filter(is_active=True).first()
    if model is None:
        logger.info("recompute_active_model_scores: no active model; nothing to do")
        return {"recomputed": 0, "modelId": None}

    user = None
    if user_id:
        user = get_user_model().objects.filter(pk=user_id).first()

    count = recompute_all_scores_for_model(model, by_user=user)
    logger.info(
        "recompute_active_model_scores: recomputed %s entities for model %s",
        count,
        model.id,
    )
    return {"recomputed": count, "modelId": str(model.id)}
