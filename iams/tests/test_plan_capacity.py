"""Capacity-constrained audit plan generation.

The plan used to be "top N by score", which meant the effort estimates on an
entity were collected and read by nothing. These tests pin the behaviour that
gives them a purpose, and the three ordering rules that are not the same as
ordering by risk:

  - a mandated engagement is never dropped to fit a higher-scoring one
  - an entity past the cycle its own rating implies comes before one that is not
  - what did not fit is reported, not silently discarded

That last one is the point of the exercise. A plan that quietly drops what it
could not afford leaves the chief audit executive with no basis for asking the
board for more resource.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from iams.models import AuditableEntity, RiskFactor, RiskFactorWeight, RiskScoringModel
from iams.risk_engine import (
    RiskEngineError,
    available_audit_days,
    generate_audit_plan_draft,
    record_score,
    select_plan_entities,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def sa_client(super_admin, authed_client):
    return authed_client(super_admin)


@pytest.fixture
def model(db):
    m = RiskScoringModel.objects.create(
        name="Planning", version="1.0",
        formula=RiskScoringModel.FORMULA_IMPACT_LIKELIHOOD, is_active=True,
    )
    for code, group in (("exposure", "impact"), ("controls", "likelihood")):
        factor = RiskFactor.objects.create(
            code=code, name=code.title(), group=group, scale_min=1, scale_max=5,
        )
        RiskFactorWeight.objects.create(scoring_model=m, factor=factor, weight=100)
    return m


def _entity(name, *, days=None, rating="Medium", mandated=False, last_audit=None, **kw):
    return AuditableEntity.objects.create(
        name=name,
        estimated_ia_days=Decimal(str(days)) if days is not None else None,
        risk_rating=rating,
        is_mandatory_to_audit=mandated,
        last_audit_date=last_audit,
        **kw,
    )


def _score(model, entity, exposure, controls=3):
    return record_score(
        entity, model=model, factor_values={"exposure": exposure, "controls": controls},
    )


def _scored_rows(model):
    from iams.models import EntityRiskScore

    return list(
        EntityRiskScore.objects.filter(scoring_model=model, is_current=True)
        .select_related("entity")
        .order_by("-composite_score", "entity__name")
    )


# ══════════════════════════════════════════════════════════════════════
# Capacity arithmetic
# ══════════════════════════════════════════════════════════════════════
def test_available_days_follows_the_planning_convention():
    """6 auditors x 230 days x 65% direct, less a 15% reserve."""
    budget = available_audit_days({
        "auditors": 6, "workingDaysPerAuditor": 230,
        "directAuditRatio": "0.65", "reservePercent": "0.15",
    })
    assert budget["gross"] == Decimal("897.00")
    assert budget["reserve"] == Decimal("134.55")
    assert budget["available"] == Decimal("762.45")


def test_capacity_defaults_are_applied():
    budget = available_audit_days({"auditors": 1})
    assert budget["gross"] == Decimal("149.50")


@pytest.mark.parametrize(
    "capacity",
    [
        {"auditors": 0},
        {"auditors": 3, "directAuditRatio": "1.5"},
        {"auditors": 3, "reservePercent": "1.0"},
    ],
)
def test_nonsense_capacity_is_rejected(capacity):
    with pytest.raises(RiskEngineError):
        available_audit_days(capacity)


# ══════════════════════════════════════════════════════════════════════
# Selection
# ══════════════════════════════════════════════════════════════════════
def test_selection_stops_when_the_days_run_out(model):
    recent = date.today() - timedelta(days=30)
    for name, exposure in (("A", 5), ("B", 4), ("C", 3), ("D", 2)):
        _score(model, _entity(name, days=40, rating="Low", last_audit=recent), exposure)

    result = select_plan_entities(_scored_rows(model), capacity={"auditors": 1})
    # 1 auditor -> 149.50 gross, 127.08 available after reserve -> three at 40d.
    assert [r["entity"].name for r in result["selected"]] == ["A", "B", "C"]
    assert [r["entity"].name for r in result["spilled"]] == ["D"]
    assert result["capacity"]["used"] == Decimal("120.00")


def test_the_reserve_is_never_spent(model):
    recent = date.today() - timedelta(days=30)
    _score(model, _entity("Big", days=140, rating="Low", last_audit=recent), 5)

    result = select_plan_entities(_scored_rows(model), capacity={"auditors": 1})
    # 140 days exceeds the 127.08 available, even though gross is 149.50.
    assert result["selected"] == []
    assert [r["entity"].name for r in result["spilled"]] == ["Big"]


def test_a_mandated_engagement_is_taken_even_when_it_blows_the_budget(model):
    """Dropping a compulsory review is a compliance failure, not a trade-off.

    The engagement here costs more than the whole available budget. It is still
    selected, the plan is reported as over-committed, and the discretionary work
    spills — which is the conversation the chief audit executive needs to have
    with the board, not a number the tool quietly rounds away.
    """
    recent = date.today() - timedelta(days=30)
    _score(model, _entity("High risk", days=60, rating="Low", last_audit=recent), 5)
    _score(
        model,
        _entity("Regulatory return", days=200, rating="Low", mandated=True, last_audit=recent),
        1,
    )

    result = select_plan_entities(_scored_rows(model), capacity={"auditors": 1})

    assert [r["entity"].name for r in result["selected"]] == ["Regulatory return"]
    assert result["selected"][0]["reason"] == "mandated"
    assert [r["entity"].name for r in result["spilled"]] == ["High risk"]
    # 200 days against 127.08 available.
    assert result["capacity"]["overCommitted"] is True


def test_a_mandated_engagement_does_not_starve_the_rest_when_it_fits(model):
    """The rule is "never dropped", not "always alone"."""
    recent = date.today() - timedelta(days=30)
    _score(model, _entity("High risk", days=30, rating="Low", last_audit=recent), 5)
    _score(
        model,
        _entity("Regulatory return", days=30, rating="Low", mandated=True, last_audit=recent),
        1,
    )

    result = select_plan_entities(_scored_rows(model), capacity={"auditors": 1})

    assert [r["entity"].name for r in result["selected"]] == [
        "Regulatory return", "High risk",
    ]
    assert result["spilled"] == []
    assert result["capacity"]["overCommitted"] is False


def test_overdue_entities_outrank_higher_scoring_current_ones(model):
    recent = date.today() - timedelta(days=30)
    long_ago = date.today() - timedelta(days=365 * 4)
    _score(model, _entity("Current but risky", days=10, rating="Low", last_audit=recent), 5)
    _score(model, _entity("Stale", days=10, rating="Low", last_audit=long_ago), 1)

    result = select_plan_entities(_scored_rows(model), capacity={"auditors": 1})
    assert [r["entity"].name for r in result["selected"]] == ["Stale", "Current but risky"]
    assert result["selected"][0]["reason"] == "overdue"


def test_a_never_audited_entity_counts_as_overdue(model):
    recent = date.today() - timedelta(days=30)
    _score(model, _entity("Seen recently", days=10, rating="Low", last_audit=recent), 5)
    _score(model, _entity("Never looked at", days=10, rating="Low"), 1)

    result = select_plan_entities(_scored_rows(model), capacity={"auditors": 1})
    assert result["selected"][0]["entity"].name == "Never looked at"


def test_entities_below_the_readiness_gate_are_excluded_and_reported(model):
    """Planning off an incomplete record is guessing with extra steps."""
    _score(model, _entity("Half-filled", days=10), 5)

    result = select_plan_entities(_scored_rows(model), min_readiness=80)
    assert result["selected"] == []
    assert [e.name for e in result["excluded_unassessed"]] == ["Half-filled"]


def test_an_entity_with_no_estimate_is_planned_but_flagged(model):
    """Excluding it would silently drop a high-risk unit over a blank field."""
    _score(model, _entity("No estimate", days=None), 5)

    result = select_plan_entities(_scored_rows(model), capacity={"auditors": 2})
    assert [r["entity"].name for r in result["selected"]] == ["No estimate"]
    assert [e.name for e in result["unestimated"]] == ["No estimate"]


def test_top_n_still_caps_an_uncapacitated_plan(model):
    for i in range(5):
        _score(model, _entity(f"E{i}", days=5), 5 - (i % 5))

    result = select_plan_entities(_scored_rows(model), top_n=2)
    assert len(result["selected"]) == 2
    assert len(result["spilled"]) == 3


# ══════════════════════════════════════════════════════════════════════
# End to end
# ══════════════════════════════════════════════════════════════════════
def test_draft_records_what_did_not_fit(model, super_admin):
    recent = date.today() - timedelta(days=30)
    for name, exposure in (("A", 5), ("B", 4), ("C", 3)):
        _score(model, _entity(name, days=80, rating="Low", last_audit=recent), exposure)

    req = generate_audit_plan_draft(
        model=model, year=2027, requested_by=super_admin,
        capacity={"auditors": 1},
    )

    assert "Not included for capacity reasons" in req.description
    assert "Capacity:" in req.description
    summary = req._plan_summary
    assert [row["name"] for row in summary["selected"]] == ["A"]
    assert {row["name"] for row in summary["spilled"]} == {"B", "C"}
    assert summary["capacity"]["available"] == "127.08"


def test_generate_plan_endpoint_accepts_capacity(sa_client, model, super_admin):
    _score(model, _entity("Claims", days=20), 5)

    resp = sa_client.post(
        "/api/risk/generate-plan/",
        {
            "scoringModelId": str(model.id),
            "year": 2027,
            "capacity": {"auditors": 4, "reservePercent": "0.1"},
        },
        format="json",
    )
    assert resp.status_code == 201, resp.data
    assert resp.data["planSummary"]["capacity"]["available"] == "538.20"
    assert resp.data["planSummary"]["selected"][0]["name"] == "Claims"


def test_generate_plan_rejects_a_malformed_capacity(sa_client, model, super_admin):
    _score(model, _entity("Claims", days=20), 5)

    resp = sa_client.post(
        "/api/risk/generate-plan/",
        {"scoringModelId": str(model.id), "year": 2027, "capacity": "six auditors"},
        format="json",
    )
    assert resp.status_code == 400
    assert "capacity" in resp.data
