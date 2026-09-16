"""Conformance tests for the IIA risk-factor scoring approach.

The ``impact_likelihood`` formula implements Appendix F of the IIA Global
Practice Guide *Developing a Risk-Based Internal Audit Plan* (2nd ed., 2025).
That appendix publishes a fully worked example — six factors with weights, and
five auditable units with their ratings and resulting total risk scores — so
our engine can be checked against a published reference rather than against
our own arithmetic.

``test_iia_appendix_f_worked_example`` is the anchor: if it fails, our scoring
has diverged from the guide, whatever the rest of the suite says.

Also covered:
  - group subtotals are weighted averages, so percentage weights (50/35/20/10)
    and fractional weights (0.5/0.35/0.2/0.1) give the same answer
  - the normalized 0..100 composite lands in the same qualitative band as the
    guide's native 2..10 score, for every row of the worked example
  - a model with no impact/likelihood factors raises rather than scoring 0
  - factors deactivated mid-life drop out of both subtotals
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from iams.models import (
    AuditableEntity,
    RiskFactor,
    RiskFactorGroupChoices,
    RiskFactorWeight,
    RiskScoringModel,
)
from iams.risk_engine import (
    RiskEngineError,
    band_for_composite,
    compute_composite,
    impact_likelihood_detail,
    record_score,
)

pytestmark = pytest.mark.django_db


# IIA GPG 2nd ed., Appendix F, Figure F.2 — factor set and weights.
FACTORS = [
    ("loss_exposure", RiskFactorGroupChoices.IMPACT, 50),
    ("strategic_risk", RiskFactorGroupChoices.IMPACT, 50),
    ("control_environment", RiskFactorGroupChoices.LIKELIHOOD, 35),
    ("complexity", RiskFactorGroupChoices.LIKELIHOOD, 35),
    ("assurance_coverage", RiskFactorGroupChoices.LIKELIHOOD, 20),
    ("management_awareness", RiskFactorGroupChoices.LIKELIHOOD, 10),
]

# Figure F.2 rows: unit -> (ratings, impact subtotal, likelihood subtotal,
# total risk score, the guide's own band from the Total Risk Score Key).
# Key: 2-4 Low, 4.1-6.5 Moderate, 6.6-8.5 High, 8.6-10 Very High.
WORKED_EXAMPLE = {
    "Unit 1": (
        {"loss_exposure": 1, "strategic_risk": 2, "control_environment": 2,
         "complexity": 1, "assurance_coverage": 3, "management_awareness": 1},
        Decimal("1.50"), Decimal("1.75"), Decimal("3.25"), "Low",
    ),
    "Unit 2": (
        {"loss_exposure": 5, "strategic_risk": 5, "control_environment": 3,
         "complexity": 1, "assurance_coverage": 5, "management_awareness": 1},
        Decimal("5.00"), Decimal("2.50"), Decimal("7.50"), "High",
    ),
    "Unit 3": (
        {"loss_exposure": 1, "strategic_risk": 5, "control_environment": 4,
         "complexity": 5, "assurance_coverage": 4, "management_awareness": 2},
        Decimal("3.00"), Decimal("4.15"), Decimal("7.15"), "High",
    ),
    "Unit 4": (
        {"loss_exposure": 5, "strategic_risk": 5, "control_environment": 5,
         "complexity": 4, "assurance_coverage": 5, "management_awareness": 4},
        Decimal("5.00"), Decimal("4.55"), Decimal("9.55"), "Very High",
    ),
    "Unit 5": (
        {"loss_exposure": 5, "strategic_risk": 2, "control_environment": 4,
         "complexity": 2, "assurance_coverage": 2, "management_awareness": 4},
        Decimal("3.50"), Decimal("2.90"), Decimal("6.40"), "Moderate",
    ),
}

# How the guide's four-band key maps onto RiskRatingChoices, which the rest of
# the app (badges, filters, heat map, BusinessUnit.risk_appetite) already uses.
GUIDE_BAND_TO_APP_BAND = {
    "Low": "Low",
    "Moderate": "Medium",
    "High": "High",
    "Very High": "Critical",
}


def _build_model(
    weights=None,
    formula=RiskScoringModel.FORMULA_IMPACT_LIKELIHOOD,
    suffix="",
):
    """Create the Appendix F model.

    ``weights`` overrides the default scale; ``suffix`` namespaces the model
    name and the factor codes so a single test can build two models side by
    side (both ``RiskScoringModel(name, version)`` and ``RiskFactor.code`` are
    unique).
    """
    model = RiskScoringModel.objects.create(
        name=f"IIA Appendix F{suffix}",
        version="1.0",
        formula=formula,
        high_risk_threshold=Decimal("60"),
    )
    for code, group, default_weight in FACTORS:
        factor = RiskFactor.objects.create(
            code=f"{code}{suffix}",
            name=code.replace("_", " ").title(),
            group=group,
            scale_min=1,
            scale_max=5,
        )
        weight = default_weight if weights is None else weights[code]
        RiskFactorWeight.objects.create(
            scoring_model=model, factor=factor, weight=Decimal(str(weight)),
        )
    return model


# ──────────────────────────────────────────────────────────────────────
# The anchor test
# ──────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("unit", list(WORKED_EXAMPLE))
def test_iia_appendix_f_worked_example(unit):
    """Our subtotals and total match the guide's published figures exactly."""
    model = _build_model()
    values, want_impact, want_likelihood, want_total, _band = WORKED_EXAMPLE[unit]

    detail = impact_likelihood_detail(model, values)

    assert detail["impact_subtotal"] == want_impact
    assert detail["likelihood_subtotal"] == want_likelihood
    assert detail["raw_composite"] == want_total


@pytest.mark.parametrize("unit", list(WORKED_EXAMPLE))
def test_normalized_band_agrees_with_guide_band(unit):
    """The 0..100 composite lands in the same band as the guide's 2..10 score.

    The engine ranks and thresholds on the normalized score, while auditors
    read the native one. If the two ever disagreed, an entity could show as
    "High" in the UI and be treated as "Medium" by the planner.
    """
    model = _build_model()
    values, _i, _l, _total, guide_band = WORKED_EXAMPLE[unit]

    composite = compute_composite(model, values)

    assert band_for_composite(composite) == GUIDE_BAND_TO_APP_BAND[guide_band]


def test_percentage_and_fractional_weights_are_equivalent():
    """50/35/20/10 and 0.5/0.35/0.2/0.1 score identically.

    Group subtotals divide by the group's own total weight, so an administrator
    can express weights either way without silently changing every score.
    """
    values, _i, _l, want_total, _b = WORKED_EXAMPLE["Unit 4"]

    pct = _build_model(suffix="_pct")
    frac = _build_model(suffix="_frac", weights={
        "loss_exposure": "0.50", "strategic_risk": "0.50",
        "control_environment": "0.35", "complexity": "0.35",
        "assurance_coverage": "0.20", "management_awareness": "0.10",
    })
    # Factor codes are namespaced per model, so the ratings must be too.
    pct_values = {f"{k}_pct": v for k, v in values.items()}
    frac_values = {f"{k}_frac": v for k, v in values.items()}

    assert impact_likelihood_detail(pct, pct_values)["raw_composite"] == want_total
    assert impact_likelihood_detail(frac, frac_values)["raw_composite"] == want_total
    assert compute_composite(pct, pct_values) == compute_composite(frac, frac_values)


def test_deactivated_factor_drops_out_of_its_subtotal():
    """Deactivating a factor removes it from the subtotal and reweights."""
    model = _build_model()
    values = WORKED_EXAMPLE["Unit 4"][0]

    before = impact_likelihood_detail(model, values)["impact_subtotal"]
    assert before == Decimal("5.00")

    RiskFactor.objects.filter(code="strategic_risk").update(is_active=False)
    after = impact_likelihood_detail(model, values)

    # Only loss_exposure remains in the impact group; its rating is 5, and a
    # one-factor weighted average is just that rating.
    assert after["impact_subtotal"] == Decimal("5.00")
    assert len(after) == 4


def test_model_without_grouped_factors_raises():
    """A model whose factors are all 'standalone' cannot use this formula.

    Scoring 0 would be worse than failing: it would rank every entity equally
    and quietly produce an audit plan with no risk ordering at all.
    """
    model = RiskScoringModel.objects.create(
        name="Ungrouped", version="1.0",
        formula=RiskScoringModel.FORMULA_IMPACT_LIKELIHOOD,
    )
    factor = RiskFactor.objects.create(
        code="ungrouped", name="Ungrouped",
        group=RiskFactorGroupChoices.STANDALONE, scale_min=1, scale_max=5,
    )
    RiskFactorWeight.objects.create(scoring_model=model, factor=factor, weight=1)

    with pytest.raises(RiskEngineError, match=r"impact.*likelihood.*group"):
        compute_composite(model, {"ungrouped": 3})


def test_out_of_range_value_still_rejected():
    """Bounds checking is shared with the other formulas."""
    model = _build_model()
    values = dict(WORKED_EXAMPLE["Unit 1"][0], loss_exposure=9)

    with pytest.raises(RiskEngineError, match="out of range"):
        compute_composite(model, values)


def test_record_score_persists_the_normalized_composite():
    """A snapshot stores the normalized score and freezes the model config."""
    model = _build_model()
    model.is_active = True
    model.save()
    entity = AuditableEntity.objects.create(name="Claims handling")
    values, _i, _l, _total, _b = WORKED_EXAMPLE["Unit 4"]

    score = record_score(entity, model=model, factor_values=values)

    assert score.composite_score == compute_composite(model, values)
    assert score.is_current is True
    assert score.is_high_risk is True
    assert score.model_snapshot["formula"] == RiskScoringModel.FORMULA_IMPACT_LIKELIHOOD
    assert {f["code"] for f in score.model_snapshot["factors"]} == {c for c, _g, _w in FACTORS}
