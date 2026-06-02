"""Roll-up of per-entity ``EntityRisk`` line items into the owning
``AuditableEntity``'s likelihood / impact / risk_rating.

Policy (confirmed in planning):
  * The entity's position is driven by its worst residual risk -- the
    line item with the highest residual likelihood*impact. The L and I
    are taken from that single risk as a coherent pair (so it plots on a
    real heat-map cell). Tie-break: higher impact, then higher likelihood.
  * Risks in the ``Closed`` status are ignored; everything else (Open,
    Mitigated, Accepted) still carries residual risk the org bears.
  * Each of likelihood / impact / risk_rating is written only when the
    matching ``*_is_overridden`` flag on the entity is False. Manual
    overrides always win.
  * Rating bands match the canonical 1-25 model used on the frontend
    (``src/lib/risk-score.ts``): Low 1-5, Medium 6-11, High 12-19,
    Critical 20-25.
"""

from __future__ import annotations

from .models import AuditableEntity, EntityRisk, RiskHistoryEntry


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
    """Pure computation — the rolled-up values regardless of overrides.

    Returns ``{"likelihood", "impact", "rating"}`` (values may be ``None``
    when the entity has no open risks).
    """
    worst = _worst_risk(entity)
    if worst is None:
        return {"likelihood": None, "impact": None, "rating": None}
    likelihood = worst.effective_likelihood
    impact = worst.effective_impact
    return {
        "likelihood": likelihood,
        "impact": impact,
        "rating": score_to_rating(likelihood * impact),
    }


def recompute_entity_risk_position(entity: AuditableEntity) -> AuditableEntity:
    """Apply the roll-up to the entity, respecting per-field overrides.

    Persists only the changed, non-overridden fields, and records a
    ``RiskHistoryEntry`` when the effective rating changes. Returns the
    (possibly updated) entity.
    """
    computed = compute_entity_risk_position(entity)
    previous_rating = entity.risk_rating
    update_fields: list[str] = []

    if (
        not entity.likelihood_is_overridden
        and computed["likelihood"] is not None
        and entity.inherent_likelihood != computed["likelihood"]
    ):
        entity.inherent_likelihood = computed["likelihood"]
        update_fields.append("inherent_likelihood")

    if (
        not entity.impact_is_overridden
        and computed["impact"] is not None
        and entity.inherent_impact != computed["impact"]
    ):
        entity.inherent_impact = computed["impact"]
        update_fields.append("inherent_impact")

    if (
        not entity.risk_rating_is_overridden
        and computed["rating"] is not None
        and entity.risk_rating != computed["rating"]
    ):
        entity.risk_rating = computed["rating"]
        update_fields.append("risk_rating")

    if not update_fields:
        return entity

    update_fields.append("updated_at")
    entity.save(update_fields=update_fields)

    if "risk_rating" in update_fields and entity.risk_rating != previous_rating:
        RiskHistoryEntry.objects.create(
            entity=entity.name,
            entity_ref=entity,
            date=entity.updated_at.date(),
            previous_rating=previous_rating,
            current_rating=entity.risk_rating,
            reason="Recomputed from entity risks",
        )

    return entity
