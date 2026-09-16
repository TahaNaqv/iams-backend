"""Configurable risk scoring engine.

Three formulas, picked per ``RiskScoringModel.formula``:

  - weighted_sum         ``Σ (v_i · w_i)``      normalized to 0..100
  - weighted_avg         ``Σ (v_i · w_i) / Σ w_i``  rescaled to 0..100
  - multiplicative       designed for two factors (``likelihood`` and
                         ``impact``). Returns ``v_l · v_i`` rescaled to
                         0..100 across the product space.
  - impact_likelihood    the IIA risk-factor approach: weight the
                         impact-group factors into one subtotal and the
                         likelihood-group factors into another, then combine.
                         Native scale is 2..10 (see
                         ``impact_likelihood_detail``); the composite is
                         normalized like the rest.

All composites are returned in **normalized 0..100 space** so the
high-risk threshold + ranking are formula-agnostic. The original
factor values stay in their native scale within ``factor_values`` for
auditability and version history.

Public verbs:

  - ``compute_composite(model, factor_values)`` → Decimal
  - ``record_score(entity, model, factor_values, by_user)`` → snapshot a
    new ``EntityRiskScore`` row, flip ``is_current`` on the prior one,
    auto-bump ``entity.risk_rating`` when above the high-risk threshold.
  - ``recompute_ranks(model)`` → rebuild dense ranks across all current
    scores for a model (rank 1 = highest composite).
  - ``heat_map(model)`` → likelihood × impact 5x5 buckets with entity counts.
  - ``generate_audit_plan_draft(model, year, top_n, requested_by)`` →
    pick top-N current scores by composite, create a draft ApprovalRequest
    of type "Audit Plan".
"""
from __future__ import annotations

import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from iams.models import (
    ApprovalRequest,
    AuditableEntity,
    EntityRiskScore,
    RiskFactor,
    RiskFactorGroupChoices,
    RiskScoringModel,
)

logger = logging.getLogger(__name__)
User = get_user_model()


class RiskEngineError(Exception):
    """Domain error from the risk engine."""


_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_Q = Decimal("0.01")

# ── Canonical composite (0..100) qualitative bands ─────────────────────
# Single source of truth for turning a normalized composite score into a
# Critical/High/Medium/Low label. Consumed by the dashboard heat-map and the
# frontend (mirror these exact cutoffs in ``src/lib/risk-score.ts``). Distinct
# from ``score_to_rating`` in ``risk_rollup``, which bands the 1..25 L×I space.
COMPOSITE_BANDS = (
    (Decimal("80"), "Critical"),
    (Decimal("60"), "High"),
    (Decimal("40"), "Medium"),
)


def band_for_composite(score) -> str:
    """Return the qualitative band for a 0..100 composite score."""
    value = score if isinstance(score, Decimal) else Decimal(str(score or 0))
    for threshold, label in COMPOSITE_BANDS:
        if value >= threshold:
            return label
    return "Low"


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(_Q, rounding=ROUND_HALF_UP)


def _factor_lookup(model: RiskScoringModel) -> dict[str, tuple[RiskFactor, Decimal]]:
    """Build ``{factor_code: (factor, weight)}`` for the model.

    Only **active** factors participate — deactivating a ``RiskFactor`` removes
    it from every model's composite without needing to unlink each weight row.
    """
    out: dict[str, tuple[RiskFactor, Decimal]] = {}
    for fw in model.factor_weights.select_related("factor").filter(factor__is_active=True):
        out[fw.factor.code] = (fw.factor, Decimal(fw.weight))
    return out


def next_model_version(current: str) -> str:
    """Return the next minor version string (``"1.0"`` → ``"1.1"``).

    Falls back to appending ``.1`` when the current value isn't a dotted
    numeric version.
    """
    parts = (current or "").split(".")
    if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
        return f"{parts[0]}.{int(parts[1]) + 1}"
    if len(parts) == 1 and parts[0].isdigit():
        return f"{parts[0]}.1"
    return f"{current}.1" if current else "1.1"


def _model_snapshot(model: RiskScoringModel) -> dict[str, Any]:
    """Freeze the scoring model's config for storage on a score row.

    Captures formula, high-risk threshold, and every active factor's weight +
    scale so a historical composite can be re-derived exactly, even after the
    live model is edited.
    """
    return {
        "modelId": str(model.id),
        "name": model.name,
        "version": model.version,
        "formula": model.formula,
        "highRiskThreshold": str(model.high_risk_threshold),
        "factors": [
            {
                "code": code,
                "weight": str(weight),
                "scaleMin": factor.scale_min,
                "scaleMax": factor.scale_max,
            }
            for code, (factor, weight) in _factor_lookup(model).items()
        ],
    }


def _validate_values(
    factors: dict[str, tuple[RiskFactor, Decimal]],
    factor_values: dict[str, Any],
) -> dict[str, Decimal]:
    """Coerce + bounds-check factor_values; raise ``RiskEngineError`` on bad input.

    Returns a normalized ``{code: Decimal}`` map covering every factor in
    the model. Missing factors default to ``scale_min`` (so an org can
    incrementally fill in inputs); out-of-range values raise.
    """
    out: dict[str, Decimal] = {}
    for code, (factor, _weight) in factors.items():
        raw = factor_values.get(code, factor.scale_min)
        try:
            value = Decimal(str(raw))
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise RiskEngineError(
                f"Factor '{code}' value must be numeric, got {raw!r}.",
            ) from exc
        if value < factor.scale_min or value > factor.scale_max:
            raise RiskEngineError(
                f"Factor '{code}' value {value} out of range "
                f"[{factor.scale_min}, {factor.scale_max}].",
            )
        out[code] = value
    return out


# ──────────────────────────────────────────────────────────────────────
# Scoring formulas — return Decimal in 0..100 normalized space
# ──────────────────────────────────────────────────────────────────────
def compute_composite(
    model: RiskScoringModel,
    factor_values: dict[str, Any],
) -> Decimal:
    """Compute the 0..100 normalized composite for a set of factor values."""
    factors = _factor_lookup(model)
    if not factors:
        raise RiskEngineError(
            f"Scoring model '{model.name}' has no factors; cannot score.",
        )
    values = _validate_values(factors, factor_values)

    formula = model.formula
    if formula == RiskScoringModel.FORMULA_WEIGHTED_SUM:
        # Sum normalized contributions: each (v - vmin)/(vmax - vmin) * weight
        # then divide by sum_of_weights → 0..1 → ×100.
        weighted = _ZERO
        total_weight = _ZERO
        for code, value in values.items():
            factor, weight = factors[code]
            span = Decimal(factor.scale_max - factor.scale_min)
            if span <= 0:
                continue
            normalized = (value - factor.scale_min) / span
            weighted += normalized * weight
            total_weight += weight
        if total_weight <= 0:
            return _ZERO
        return _quantize((weighted / total_weight) * _HUNDRED)

    if formula == RiskScoringModel.FORMULA_WEIGHTED_AVG:
        # Average of (value/scale_max) weighted by factor weight → 0..1 → ×100.
        weighted = _ZERO
        total_weight = _ZERO
        for code, value in values.items():
            factor, weight = factors[code]
            if factor.scale_max <= 0:
                continue
            normalized = value / Decimal(factor.scale_max)
            weighted += normalized * weight
            total_weight += weight
        if total_weight <= 0:
            return _ZERO
        return _quantize((weighted / total_weight) * _HUNDRED)

    if formula == RiskScoringModel.FORMULA_MULTIPLICATIVE:
        # Designed for two factors. If they aren't both present, fall
        # back to a uniform product → result anchored on min/max
        # cell of the matrix.
        likelihood = values.get("likelihood")
        impact = values.get("impact")
        if likelihood is None or impact is None:
            raise RiskEngineError(
                "Multiplicative formula requires factors 'likelihood' and 'impact'.",
            )
        l_factor = factors["likelihood"][0]
        i_factor = factors["impact"][0]
        max_product = Decimal(l_factor.scale_max * i_factor.scale_max)
        if max_product <= 0:
            return _ZERO
        return _quantize((likelihood * impact / max_product) * _HUNDRED)

    if formula == RiskScoringModel.FORMULA_IMPACT_LIKELIHOOD:
        detail = _impact_likelihood_detail(factors, values)
        return detail["normalized"]

    raise RiskEngineError(f"Unknown formula '{formula}'.")


# ──────────────────────────────────────────────────────────────────────
# IIA risk-factor approach
# ──────────────────────────────────────────────────────────────────────
def _group_subtotals(
    factors: dict[str, tuple[RiskFactor, Decimal]],
    values: dict[str, Decimal],
    group: str,
) -> tuple[Decimal | None, Decimal | None]:
    """Weighted average of one factor group, in native scale and 0..1.

    Returns ``(native, normalized)`` — ``(None, None)`` when the group has no
    active factors. Dividing by the group's own total weight means an admin
    can express weights as percentages (50 / 35 / 20 / 10) or as fractions
    (0.5 / 0.35 / 0.2 / 0.1) and get the same answer.
    """
    native = _ZERO
    normalized = _ZERO
    total_weight = _ZERO
    for code, (factor, weight) in factors.items():
        if factor.group != group:
            continue
        value = values[code]
        span = Decimal(factor.scale_max - factor.scale_min)
        native += value * weight
        if span > 0:
            normalized += ((value - factor.scale_min) / span) * weight
        total_weight += weight
    if total_weight <= 0:
        return None, None
    return native / total_weight, normalized / total_weight


def _impact_likelihood_detail(
    factors: dict[str, tuple[RiskFactor, Decimal]],
    values: dict[str, Decimal],
) -> dict[str, Any]:
    """Impact and likelihood subtotals plus the combined score.

    Implements the risk-factor approach set out in the IIA Global Practice
    Guide *Developing a Risk-Based Internal Audit Plan* (2nd ed.),
    Appendix F, Figure F.2: each auditable unit is rated on every factor,
    the impact-related and likelihood-related factors are weighted into two
    subtotals, and the subtotals are summed into a total risk score.

    Two numbers come back because they serve different readers:

    * ``raw_composite`` is on the guide's native 2..10 scale. Auditors
      recognise it, and it is what the scoring UI shows.
    * ``normalized`` is 0..100, matching every other formula in this engine,
      so ``high_risk_threshold``, ranking and ``band_for_composite`` stay
      formula-agnostic.

    Both are kept in step: across the guide's own five worked examples the
    normalized band and the guide's stated band agree on every row.
    """
    impact_native, impact_norm = _group_subtotals(
        factors, values, RiskFactorGroupChoices.IMPACT,
    )
    likelihood_native, likelihood_norm = _group_subtotals(
        factors, values, RiskFactorGroupChoices.LIKELIHOOD,
    )
    present = [p for p in (impact_norm, likelihood_norm) if p is not None]
    if not present:
        raise RiskEngineError(
            "The impact_likelihood formula needs at least one active factor "
            "in the 'impact' or 'likelihood' group. Set RiskFactor.group on "
            "this model's factors.",
        )
    normalized = (sum(present) / Decimal(len(present))) * _HUNDRED
    raw_parts = [p for p in (impact_native, likelihood_native) if p is not None]
    return {
        "impact_subtotal": _quantize(impact_native) if impact_native is not None else None,
        "likelihood_subtotal": (
            _quantize(likelihood_native) if likelihood_native is not None else None
        ),
        "raw_composite": _quantize(sum(raw_parts)),
        "normalized": _quantize(normalized),
    }


def impact_likelihood_detail(
    model: RiskScoringModel,
    factor_values: dict[str, Any],
) -> dict[str, Any]:
    """Public wrapper: subtotals + raw + normalized for a set of values.

    Used by the scoring UI to show the live impact/likelihood breakdown while
    an assessor is still filling the form, without writing a snapshot row.
    """
    factors = _factor_lookup(model)
    if not factors:
        raise RiskEngineError(
            f"Scoring model '{model.name}' has no factors; cannot score.",
        )
    values = _validate_values(factors, factor_values)
    return _impact_likelihood_detail(factors, values)


# ──────────────────────────────────────────────────────────────────────
# Snapshot + rank
# ──────────────────────────────────────────────────────────────────────
@transaction.atomic
def record_score(
    entity: AuditableEntity,
    *,
    model: RiskScoringModel,
    factor_values: dict[str, Any],
    by_user: User | None = None,
    notes: str = "",
    _skip_rank_rebuild: bool = False,
) -> EntityRiskScore:
    """Snapshot a new score row + flip ``is_current`` on the previous one.

    Side effects:
      - composite_score computed via the model's formula
      - ``is_high_risk`` set if composite ≥ model.high_risk_threshold
      - If high-risk, bumps ``entity.risk_rating`` to "High" (preserves
        "Critical"), mirroring the CSA weak-control flow.
      - Ranks are rebuilt across all current scores for the model.
    """
    composite = compute_composite(model, factor_values)

    # Flip previous current row off (if any). Use update() to skip the
    # auditing mixin path — we're inside the engine here.
    EntityRiskScore.objects.filter(
        entity=entity, scoring_model=model, is_current=True,
    ).update(is_current=False)

    is_high = composite >= model.high_risk_threshold
    score = EntityRiskScore.objects.create(
        entity=entity,
        scoring_model=model,
        factor_values=factor_values,
        model_snapshot=_model_snapshot(model),
        composite_score=composite,
        is_high_risk=is_high,
        is_current=True,
        snapshot_at=timezone.now(),
        snapshot_by=by_user,
        notes=notes,
    )

    # Reconcile the entity's headline rating through the SINGLE authority
    # (``resolve_entity_risk_rating``) instead of writing ``risk_rating``
    # directly here. That path:
    #   * escalates to High only when the *active* model flags high-risk
    #     (so scoring against a non-active model can't bump the rating),
    #   * preserves Critical and manual overrides,
    #   * lets a subsequent lower snapshot de-escalate a prior engine High,
    #   * writes a RiskHistoryEntry + system revision and bumps ``version``.
    from iams.risk_rollup import recompute_entity_risk_position
    recompute_entity_risk_position(entity)

    # Rebuild ranks across all current scores for the model. Skipped by the
    # bulk recompute, which rebuilds once at the end instead of once per row
    # (the per-row rebuild made ``recompute_all_scores_for_model`` O(n²)).
    if not _skip_rank_rebuild:
        recompute_ranks(model)

    return score


@transaction.atomic
def recompute_ranks(model: RiskScoringModel) -> int:
    """Assign dense ranks to all current scores for ``model``.

    Highest composite = rank 1. Ties get the same rank (1, 2, 2, 3, …).
    Returns the number of rows updated.
    """
    current = list(
        EntityRiskScore.objects
        .filter(scoring_model=model, is_current=True)
        .order_by("-composite_score", "entity_id")
    )
    if not current:
        return 0
    # Dense ranking: distinct composite values get consecutive ranks
    # (1, 1, 2, 3 — not the "standard" 1, 1, 3, 4 with gaps for ties).
    rank = 0
    last_score = None
    to_update: list[EntityRiskScore] = []
    for row in current:
        if last_score is None or row.composite_score != last_score:
            rank += 1
            last_score = row.composite_score
        if row.rank != rank:
            row.rank = rank
            to_update.append(row)
    if to_update:
        # One bulk UPDATE instead of one query per changed row (the loop was
        # O(n) queries on large universes).
        EntityRiskScore.objects.bulk_update(to_update, ["rank"])
    return len(to_update)


# ──────────────────────────────────────────────────────────────────────
# Heat map: 5x5 grid keyed by (likelihood, impact)
# ──────────────────────────────────────────────────────────────────────
def heat_map(model: RiskScoringModel) -> dict[str, Any]:
    """Build a ``likelihood × impact`` bucketed grid.

    Looks up the two factors by code (``likelihood``, ``impact``). For
    every current score, places the entity in the (l, i) bucket using
    the integer factor values. Returns a list of cells plus a
    flattened entity list for the FE's tooltip.
    """
    factors = _factor_lookup(model)
    l_factor = factors.get("likelihood", (None, None))[0]
    i_factor = factors.get("impact", (None, None))[0]
    if l_factor is None or i_factor is None:
        raise RiskEngineError(
            "heat_map requires both 'likelihood' and 'impact' factors in the model.",
        )

    cells: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for score in (
        EntityRiskScore.objects
        .filter(scoring_model=model, is_current=True)
        .select_related("entity")
    ):
        try:
            l = int(Decimal(str(score.factor_values.get("likelihood", l_factor.scale_min))))
            i = int(Decimal(str(score.factor_values.get("impact", i_factor.scale_min))))
        except (TypeError, ValueError, ArithmeticError):
            continue
        cells.setdefault((l, i), []).append({
            "entityId": str(score.entity_id),
            "entityName": score.entity.name,
            "composite": str(score.composite_score),
            "rank": score.rank,
        })

    grid = []
    for l in range(l_factor.scale_min, l_factor.scale_max + 1):
        for i in range(i_factor.scale_min, i_factor.scale_max + 1):
            entries = cells.get((l, i), [])
            grid.append({
                "likelihood": l,
                "impact": i,
                "count": len(entries),
                "entities": entries,
            })

    return {
        "likelihoodScale": [l_factor.scale_min, l_factor.scale_max],
        "impactScale": [i_factor.scale_min, i_factor.scale_max],
        "cells": grid,
    }


# ──────────────────────────────────────────────────────────────────────
# Annual plan generation (FR-PLAN-01)
# ──────────────────────────────────────────────────────────────────────
@transaction.atomic
# ──────────────────────────────────────────────────────────────────────
# Capacity
# ──────────────────────────────────────────────────────────────────────
def available_audit_days(capacity: dict) -> dict:
    """Turn a team's shape into the days actually available for engagements.

    ``auditors x working days x direct-audit ratio``, less a reserve. The
    defaults follow the convention in the planning literature: ~230 working
    days per auditor, 60-70% of that spent on direct audit work rather than
    training, administration and QA, and a 10-15% reserve so an emerging risk
    or a board request does not have to displace a planned engagement.

    The reserve is deducted, never spent: what the planner may fill is what
    comes back in ``available``.
    """
    auditors = Decimal(str(capacity.get("auditors", 0) or 0))
    per_auditor = Decimal(str(capacity.get("workingDaysPerAuditor", 230) or 230))
    direct_ratio = Decimal(str(capacity.get("directAuditRatio", "0.65") or "0.65"))
    reserve_pct = Decimal(str(capacity.get("reservePercent", "0.15") or "0.15"))

    if auditors <= 0:
        raise RiskEngineError("capacity.auditors must be greater than zero.")
    if not (0 < direct_ratio <= 1):
        raise RiskEngineError("capacity.directAuditRatio must be between 0 and 1.")
    if not (0 <= reserve_pct < 1):
        raise RiskEngineError("capacity.reservePercent must be between 0 and 1.")

    gross = auditors * per_auditor * direct_ratio
    reserve = gross * reserve_pct
    return {
        "gross": _quantize(gross),
        "reserve": _quantize(reserve),
        "available": _quantize(gross - reserve),
    }


def _entity_effort(entity) -> Decimal:
    """Estimated days for an entity, falling back to the legacy column.

    An entity with no estimate at all is treated as zero rather than excluded:
    excluding it would quietly drop a high-risk unit from the plan because
    nobody had filled in a number yet. It appears in the plan and is reported
    in ``unestimated`` so the gap is visible instead of silent.
    """
    total = getattr(entity, "total_estimated_days", None)
    return Decimal(str(total)) if total is not None else _ZERO


def _cycle_months(rating: str) -> int:
    """Months a rating implies between engagements (IIA GPG, p.20)."""
    return {"Critical": 12, "High": 12, "Medium": 24}.get(rating, 36)


def select_plan_entities(
    scored,
    *,
    capacity: dict | None = None,
    top_n: int = 20,
    min_readiness: int | None = None,
    include_mandatory: bool = True,
) -> dict:
    """Choose which entities go into a plan, and say what did not fit.

    Order of business, which is not the same as order of risk:

    1. **Mandated engagements first.** A cyclical review required by law
       competes for the same days as a risk-ranked one and has to happen even
       when its inherent risk is low (IIA GPG, "Cyclical Frequency in Highly
       Regulated Industries"). Dropping one to fit a higher-scoring entity is
       a compliance failure, not a prioritisation call.
    2. **Overdue cycles next.** An entity past the interval its own rating
       implies is already outside the cadence the plan promised.
    3. **Then risk rank**, filling until the available days run out.

    Everything that did not fit comes back in ``spilled``. That is the output
    the chief audit executive actually needs: a plan that silently drops what
    it could not afford leaves no basis for asking the board for more resource.

    ``min_readiness`` gates on record completeness. Planning off an entity with
    no objectives, no effort estimate and no assessment is not risk-based
    planning, so those are excluded and reported rather than quietly included.
    """
    budget = available_audit_days(capacity) if capacity else None
    remaining = budget["available"] if budget else None

    today = timezone.now().date()
    candidates = []
    excluded_unassessed = []

    for row in scored:
        entity = row.entity
        if min_readiness is not None:
            from iams import readiness as readiness_service

            if readiness_service.score_only(entity) < min_readiness:
                excluded_unassessed.append(entity)
                continue

        months_since = entity.months_since_last_audit
        is_mandated = bool(
            include_mandatory
            and (entity.is_mandatory_to_audit or entity.frequency_source == "Mandated")
        )
        is_overdue = (
            months_since is None or months_since >= _cycle_months(entity.risk_rating)
        )
        # Sort key: mandated first, then overdue, then by score. Negated so a
        # plain ascending sort puts the most pressing first.
        candidates.append({
            "entity": entity,
            "composite": row.composite_score,
            "days": _entity_effort(entity),
            "reason": (
                "mandated" if is_mandated
                else "overdue" if is_overdue
                else "risk rank"
            ),
            "_order": (
                0 if is_mandated else 1 if is_overdue else 2,
                -Decimal(str(row.composite_score or 0)),
                entity.name,
            ),
        })

    candidates.sort(key=lambda c: c["_order"])

    selected, spilled, unestimated = [], [], []
    used = _ZERO
    for candidate in candidates:
        days = candidate["days"]
        if days <= 0:
            unestimated.append(candidate["entity"])
        # A mandated engagement is never spilled: it is not ours to drop.
        if remaining is not None and candidate["reason"] != "mandated":
            if len(selected) >= top_n or days > remaining:
                spilled.append(candidate)
                continue
        elif remaining is None and len(selected) >= top_n:
            spilled.append(candidate)
            continue
        selected.append(candidate)
        used += days
        if remaining is not None:
            remaining = max(_ZERO, remaining - days)

    for candidate in (*selected, *spilled):
        candidate.pop("_order", None)

    result = {
        "selected": selected,
        "spilled": spilled,
        "excluded_unassessed": excluded_unassessed,
        "unestimated": unestimated,
    }
    if budget:
        result["capacity"] = {
            **budget,
            "used": _quantize(used),
            "remaining": _quantize(remaining if remaining is not None else _ZERO),
            "overCommitted": used > budget["available"],
        }
    return result


def generate_audit_plan_draft(
    *,
    model: RiskScoringModel,
    year: int,
    top_n: int = 20,
    requested_by: User,
    capacity: dict | None = None,
    min_readiness: int | None = None,
    include_mandatory: bool = True,
) -> ApprovalRequest:
    """Pick top-N current scores; create a draft Audit Plan ApprovalRequest.

    The plan goes through the existing approval chain (auto-applied via
    the Phase 2 Track 3 chain template signal). The selected entities
    + their composite scores land in the request's ``description`` (a
    line per entity) plus a structured snapshot in audit-log details.
    """
    if not requested_by or not requested_by.is_authenticated:
        raise RiskEngineError("generate_audit_plan_draft requires an authenticated user.")
    if top_n <= 0:
        raise RiskEngineError("top_n must be a positive integer.")

    scored = list(
        EntityRiskScore.objects
        .filter(scoring_model=model, is_current=True)
        .select_related("entity")
        .order_by("-composite_score", "entity__name")
    )
    if not scored:
        raise RiskEngineError(
            f"No current risk scores for model '{model.name}' — score some entities first.",
        )

    selection = select_plan_entities(
        scored,
        capacity=capacity,
        top_n=top_n,
        min_readiness=min_readiness,
        include_mandatory=include_mandatory,
    )
    top = selection["selected"]

    lines = [
        f"{rank + 1:>3}. {row['entity'].name} — composite {row['composite']} "
        f"({row['reason']}, {row['days']} days)"
        for rank, row in enumerate(top)
    ]
    description = (
        f"Draft annual audit plan for {year}: {len(top)} engagements using "
        f"scoring model '{model.name}' v{model.version} ({model.formula}).\n\n"
        + "\n".join(lines)
    )
    if capacity:
        budget = selection["capacity"]
        description += (
            f"\n\nCapacity: {budget['used']} of {budget['available']} days used "
            f"({budget['reserve']} held in reserve, {budget['gross']} gross)."
        )
    if selection["spilled"]:
        # The point of the exercise. A plan that silently drops what did not
        # fit leaves the CAE with no way to ask the board for more resource --
        # Standard 10.1 is about exactly that conversation.
        spill_lines = "\n".join(
            f"     {row['entity'].name} — composite {row['composite']}, {row['days']} days"
            for row in selection["spilled"]
        )
        spill_days = sum(Decimal(str(row["days"])) for row in selection["spilled"])
        description += (
            f"\n\nNot included for capacity reasons "
            f"({len(selection['spilled'])} engagements, {spill_days} days):\n"
            + spill_lines
        )
    if selection["excluded_unassessed"]:
        description += (
            f"\n\nExcluded as not yet assessed "
            f"(readiness below {min_readiness}%): "
            + ", ".join(e.name for e in selection["excluded_unassessed"])
        )

    # Collision-safe reference: a re-generated plan for the same year gets a
    # ``-r2``/``-r3`` suffix instead of silently duplicating ``PLAN-<year>``.
    base_ref = f"PLAN-{year}"
    reference_id = base_ref
    existing = ApprovalRequest.objects.filter(
        reference_id__startswith=base_ref
    ).count()
    if existing:
        reference_id = f"{base_ref}-r{existing + 1}"

    submitter_email = getattr(requested_by, "email", "") or requested_by.get_username()
    req = ApprovalRequest.objects.create(
        title=f"{year} Annual Audit Plan",
        type="Audit Plan",
        reference_id=reference_id,
        department="Internal Audit",
        submitted_by=submitter_email,
        submitted_date=timezone.now().date(),
        current_step=0,
        priority="High",
        description=description,
        status="Pending",
    )
    # Chain template auto-application is wired via the post_save signal
    # (iams/signals.py::approval_request_apply_chain) so the steps get
    # generated for us right after this row commits.
    # Attach a machine-readable summary so the API can return what fitted,
    # what spilled and how much capacity is left, rather than making the caller
    # parse it back out of the description.
    req._plan_summary = {
        "selected": [
            {
                "entityId": str(row["entity"].id),
                "name": row["entity"].name,
                "composite": str(row["composite"]),
                "days": str(row["days"]),
                "reason": row["reason"],
            }
            for row in selection["selected"]
        ],
        "spilled": [
            {
                "entityId": str(row["entity"].id),
                "name": row["entity"].name,
                "composite": str(row["composite"]),
                "days": str(row["days"]),
            }
            for row in selection["spilled"]
        ],
        "excludedUnassessed": [
            {"entityId": str(e.id), "name": e.name}
            for e in selection["excluded_unassessed"]
        ],
        "unestimated": [
            {"entityId": str(e.id), "name": e.name} for e in selection["unestimated"]
        ],
        "capacity": {k: str(v) for k, v in selection.get("capacity", {}).items()},
    }
    logger.info(
        "risk_engine: generated audit plan draft for year=%s, selected=%d, "
        "spilled=%d, request=%s",
        year, len(selection["selected"]), len(selection["spilled"]), req.pk,
    )
    return req


# ──────────────────────────────────────────────────────────────────────
# Bulk recompute (used after weight/formula edits)
# ──────────────────────────────────────────────────────────────────────
def recompute_all_scores_for_model(
    model: RiskScoringModel,
    *,
    by_user: User | None = None,
) -> int:
    """Re-snapshot every entity that has a current score against this model.

    Walks the latest factor_values forward into a new snapshot. Lets
    admins fix a typo'd weight and have it propagate without forcing
    every business unit to re-submit factor values.
    """
    with transaction.atomic():
        current_rows = list(
            EntityRiskScore.objects
            .filter(scoring_model=model, is_current=True)
            .select_related("entity")
        )
        count = 0
        for row in current_rows:
            # Idempotent: only re-snapshot when the recompute actually changes
            # the composite or the high-risk band. Re-running with no model
            # change is now a no-op instead of doubling history every pass.
            new_composite = compute_composite(model, row.factor_values)
            new_is_high = new_composite >= model.high_risk_threshold
            if new_composite == row.composite_score and new_is_high == row.is_high_risk:
                continue
            record_score(
                row.entity,
                model=model,
                factor_values=row.factor_values,
                by_user=by_user,
                notes="Auto-recomputed after scoring-model update.",
                _skip_rank_rebuild=True,
            )
            count += 1
        # Rebuild ranks once for the whole set instead of once per row.
        recompute_ranks(model)
    return count
