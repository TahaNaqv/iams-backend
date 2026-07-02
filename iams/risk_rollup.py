"""Roll-up of per-entity ``EntityRisk`` line items into the owning
``AuditableEntity``'s inherent / residual position and ``risk_rating``.

Policy (confirmed in planning):
  * The entity's position is driven by its worst residual risk -- the
    line item with the highest residual likelihood*impact. Both the
    inherent (pre-control) and residual (post-control) likelihood/impact
    are taken from that single driving risk as coherent pairs (so it
    plots on real heat-map cells). Tie-break: higher impact, then higher
    likelihood.
  * Risks in the ``Closed`` status are ignored; everything else (Open,
    Mitigated, Accepted) still carries residual risk the org bears.
  * ``inherent_likelihood`` / ``inherent_impact`` are written only when the
    matching ``*_is_overridden`` flag on the entity is False. Manual
    overrides always win. ``residual_likelihood`` / ``residual_impact`` are
    always auto-computed (no manual override — residual reflects the live
    control environment).
  * ``risk_rating`` is resolved by a single authority (see
    ``resolve_entity_risk_rating``): manual override → active scoring-model
    score → residual worst-risk band → default. Neither the roll-up nor the
    scoring engine writes ``risk_rating`` directly any more.
  * When there are no open risks (and no higher-precedence source), the
    residual position is cleared and the rating falls back to the default —
    a rating no longer goes stale after every risk is closed.
  * Rating bands match the canonical 1-25 model used on the frontend
    (``src/lib/risk-score.ts``): Low 1-5, Medium 6-11, High 12-19,
    Critical 20-25.
"""

from __future__ import annotations

from .models import (
    AuditableEntity,
    EntityRisk,
    RiskHistoryEntry,
)


def score_to_rating(score: int) -> str:
    if score >= 20:
        return "Critical"
    if score >= 12:
        return "High"
    if score >= 6:
        return "Medium"
    return "Low"


def _worst_risk(entity: AuditableEntity) -> EntityRisk | None:
    """The driving (highest residual score) non-closed risk, or None."""
    candidates = [r for r in entity.risks.all() if r.status != "Closed"]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda r: (r.residual_score, r.effective_impact, r.effective_likelihood),
    )


def compute_entity_risk_position(entity: AuditableEntity) -> dict:
    """Pure computation of the rolled-up position from the entity's risks.

    Returns inherent + residual likelihood/impact and the residual-banded
    rating. All values are ``None`` when the entity has no open risks.
    """
    worst = _worst_risk(entity)
    if worst is None:
        return {
            "inherent_likelihood": None,
            "inherent_impact": None,
            "residual_likelihood": None,
            "residual_impact": None,
            "rating": None,
        }
    return {
        "inherent_likelihood": worst.inherent_likelihood,
        "inherent_impact": worst.inherent_impact,
        "residual_likelihood": worst.effective_likelihood,
        "residual_impact": worst.effective_impact,
        "rating": score_to_rating(
            worst.effective_likelihood * worst.effective_impact
        ),
    }


# Severity ordering for escalate-only reconciliation and subtree roll-ups.
RATING_SEVERITY = {"Low": 1, "Medium": 2, "High": 3, "Critical": 4}
_RATING_SEVERITY = RATING_SEVERITY  # backwards-compatible alias


def _worst_rating(*ratings: str | None) -> str | None:
    present = [r for r in ratings if r]
    if not present:
        return None
    return max(present, key=lambda r: _RATING_SEVERITY.get(r, 0))


def _engine_is_high_risk(entity: AuditableEntity) -> bool:
    """True when the active scoring model's current snapshot is high-risk.

    The ``RiskScoringModel`` emits a binary high-risk signal per entity
    (``EntityRiskScore.is_high_risk``); risk-based audit planning uses it to
    escalate the headline rating. Returns False when no active model has
    scored this entity.
    """
    from .models import EntityRiskScore, RiskScoringModel

    model = RiskScoringModel.objects.filter(is_active=True).first()
    if model is None:
        return False
    return EntityRiskScore.objects.filter(
        entity=entity, scoring_model=model, is_current=True, is_high_risk=True
    ).exists()


def resolve_entity_risk_rating(entity: AuditableEntity, residual_rating: str | None) -> str:
    """Single authority for ``risk_rating`` (escalate-only reconciliation).

    Order of resolution:

    1. Manual override (``risk_rating_is_overridden``) — the existing value
       always wins.
    2. Base rating = the residual worst-risk band, or (when there are no open
       risks) the entity's current rating — never silently downgraded to a
       default.
    3. If the active scoring model flags the entity high-risk, escalate the
       base to at least ``High`` (mirrors ``risk_engine.record_score``).
    4. ``Critical`` is never downgraded by the engine step (``_worst_rating``
       keeps the most severe).

    This ends the two-writer conflict: the engine and the line-item roll-up
    now feed a single resolver instead of both writing ``risk_rating``.
    """
    if entity.risk_rating_is_overridden:
        return entity.risk_rating
    base = residual_rating or entity.risk_rating
    if _engine_is_high_risk(entity):
        return _worst_rating(base, "High") or "High"
    return base


def recompute_entity_risk_position(entity: AuditableEntity) -> AuditableEntity:
    """Apply the roll-up to the entity, respecting per-field overrides.

    Persists only changed fields, records a ``RiskHistoryEntry`` and an
    ``AuditableEntityRevision`` when the effective rating changes, and bumps
    ``version`` so a risk-driven rating change is visible to the optimistic
    lock and the Revisions tab. Returns the (possibly updated) entity.
    """
    computed = compute_entity_risk_position(entity)
    previous_rating = entity.risk_rating
    update_fields: list[str] = []

    # Inherent (pre-control) — respects manual overrides.
    if (
        not entity.likelihood_is_overridden
        and entity.inherent_likelihood != computed["inherent_likelihood"]
    ):
        entity.inherent_likelihood = computed["inherent_likelihood"]
        update_fields.append("inherent_likelihood")
    if (
        not entity.impact_is_overridden
        and entity.inherent_impact != computed["inherent_impact"]
    ):
        entity.inherent_impact = computed["inherent_impact"]
        update_fields.append("inherent_impact")

    # Residual (post-control) — always auto-computed.
    if entity.residual_likelihood != computed["residual_likelihood"]:
        entity.residual_likelihood = computed["residual_likelihood"]
        update_fields.append("residual_likelihood")
    if entity.residual_impact != computed["residual_impact"]:
        entity.residual_impact = computed["residual_impact"]
        update_fields.append("residual_impact")

    # Rating via the single resolver (override → engine → residual → default).
    resolved_rating = resolve_entity_risk_rating(entity, computed["rating"])
    if entity.risk_rating != resolved_rating:
        entity.risk_rating = resolved_rating
        update_fields.append("risk_rating")

    if not update_fields:
        return entity

    rating_changed = "risk_rating" in update_fields
    if rating_changed:
        # A rating change is a material state change: bump the optimistic-lock
        # version so it can't be silently clobbered by a stale writer.
        entity.version = (entity.version or 0) + 1
        update_fields.append("version")
    update_fields.append("updated_at")
    entity.save(update_fields=update_fields)

    if rating_changed and entity.risk_rating != previous_rating:
        RiskHistoryEntry.objects.create(
            entity=entity.name,
            entity_ref=entity,
            date=entity.updated_at.date(),
            previous_rating=previous_rating,
            current_rating=entity.risk_rating,
            reason="Recomputed from entity risks",
        )
        _record_system_revision(entity, previous_rating)

    return entity


def _record_system_revision(entity: AuditableEntity, previous_rating: str) -> None:
    """Append a system-authored revision for a risk-driven rating change.

    Keeps the Revisions tab honest for changes that don't flow through the
    viewset (a risk edited via admin / import / signal). ``changed_by`` is
    ``None`` — the actor is the system roll-up, not a request user.
    """
    from django.db import transaction

    from .models import AuditableEntityRevision

    try:
        # Savepoint-scoped so a rare (entity, version) collision rolls back
        # only this revision insert, never the surrounding transaction.
        with transaction.atomic():
            AuditableEntityRevision.objects.create(
                entity=entity,
                version=entity.version or 1,
                changed_by=None,
                changes={
                    "risk_rating": {"from": previous_rating, "to": entity.risk_rating}
                },
                comment="Rating recomputed from entity risks.",
            )
    except Exception:  # noqa: BLE001 — a revision failure must not break the roll-up
        pass
