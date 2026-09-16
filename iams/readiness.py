"""Universe readiness: how complete an auditable entity's record is.

A universe is built in bulk and refined over time, so the v2 create form asks
for very little. What stops that leaving a register full of half-filled rows is
a visible score per entity, and a gate: only entities that reach **Assessed**
are eligible for automatic inclusion in a generated audit plan.

That gate is the point. Planning off a record with no objectives, no effort
estimate and no risk assessment is not risk-based planning; it is guessing with
extra steps. Making the threshold explicit means the CAE can say which entities
were considered and which were excluded for being incomplete — see
``unassessedExcluded`` in the plan generator.

The criteria and weights below implement §7 of
``docs/AUDIT-UNIVERSE-FORM-SPEC.md``.
"""
from __future__ import annotations

from dataclasses import dataclass

# Bands. ``ASSESSED_THRESHOLD`` is the plan-eligibility gate.
DRAFT_THRESHOLD = 40
ASSESSED_THRESHOLD = 80

BAND_DRAFT = "Draft"
BAND_PARTIAL = "Partial"
BAND_ASSESSED = "Assessed"


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    weight: int
    hint: str


CRITERIA: tuple[Criterion, ...] = (
    Criterion(
        "hasOwner", "Process owner assigned", 15,
        "Someone has to answer for this area before an engagement can be scoped.",
    ),
    Criterion(
        "hasObjectives", "Audit objectives stated", 15,
        "What an engagement here would set out to establish.",
    ),
    Criterion(
        "hasScope", "Scope boundary defined", 15,
        "What this unit covers, so neighbouring entities do not overlap.",
    ),
    Criterion(
        "hasMateriality", "At least one size or materiality figure", 10,
        "Gives the loss-exposure risk factor something to stand on.",
    ),
    Criterion(
        "hasCurrentRiskScore", "Scored against the active risk model", 30,
        "The documented assessment Standard 9.4 requires the plan to rest on.",
    ),
    Criterion(
        "hasEffortEstimate", "Effort estimate recorded", 15,
        "Without it the entity cannot be fitted into a capacity-constrained plan.",
    ),
)

# NOTE — the spec (§7) also listed "audit frequency and its basis set" as a
# 10-point criterion. It was dropped during implementation because it is
# vacuous: ``audit_frequency`` defaults to Annual and ``frequency_source`` to
# RiskBased, so every entity satisfies it the moment it is created. Keeping it
# would have reported 10% readiness for a completely empty record -- implying
# work had been done when none had -- and would have made the 80% plan-
# eligibility gate reachable with only 70% of the real work. Its 10 points went
# to the two criteria that most determine whether an entity can actually be
# planned: the risk assessment (25 -> 30) and the effort estimate (10 -> 15).

MAX_SCORE = sum(c.weight for c in CRITERIA)


def band_for(score: int) -> str:
    if score >= ASSESSED_THRESHOLD:
        return BAND_ASSESSED
    if score >= DRAFT_THRESHOLD:
        return BAND_PARTIAL
    return BAND_DRAFT


def _has_current_risk_score(entity) -> bool:
    """True when the entity carries a current score from the *active* model.

    Deliberately tied to the active model rather than to any score: a snapshot
    taken against a model that has since been superseded is history, not a
    current assessment, and planning off it would quietly use last year's
    weights.
    """
    scores = getattr(entity, "_prefetched_current_scores", None)
    if scores is not None:
        return bool(scores)
    from iams.models import EntityRiskScore

    return EntityRiskScore.objects.filter(
        entity=entity, is_current=True, scoring_model__is_active=True,
    ).exists()


def _met(entity, key: str) -> bool:
    if key == "hasOwner":
        return entity.primary_owner_id is not None
    if key == "hasObjectives":
        return bool((entity.audit_objectives or "").strip())
    if key == "hasScope":
        return bool((entity.scope_inclusions or "").strip())
    if key == "hasMateriality":
        # Reads the denormalised cache rather than counting rows: it is
        # maintained on every write and keeps this cheap enough to compute for
        # a whole page of the register.
        return bool(entity.materiality_cache)
    if key == "hasCurrentRiskScore":
        return _has_current_risk_score(entity)
    if key == "hasEffortEstimate":
        # The legacy column counts: entities predating the IA / co-source split
        # still carry a perfectly good figure there.
        return any(
            v is not None
            for v in (
                entity.estimated_ia_days,
                entity.estimated_cosource_days,
                entity.estimated_man_days,
            )
        )
    raise ValueError(f"Unknown readiness criterion {key!r}.")


def compute(entity) -> dict:
    """Full readiness breakdown for one entity.

    Returns the score, the band, and every criterion with whether it is met —
    the breakdown is what makes the number actionable, so the form can say
    "add an effort estimate" rather than just "62%".
    """
    criteria = []
    score = 0
    for criterion in CRITERIA:
        met = _met(entity, criterion.key)
        if met:
            score += criterion.weight
        criteria.append({
            "key": criterion.key,
            "label": criterion.label,
            "weight": criterion.weight,
            "hint": criterion.hint,
            "met": met,
        })
    return {
        "score": score,
        "band": band_for(score),
        "isPlanEligible": score >= ASSESSED_THRESHOLD,
        "criteria": criteria,
        "missing": [c["key"] for c in criteria if not c["met"]],
    }


def score_only(entity) -> int:
    """Just the number, for list projections."""
    return sum(c.weight for c in CRITERIA if _met(entity, c.key))
