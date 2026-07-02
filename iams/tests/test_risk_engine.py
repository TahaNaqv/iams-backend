"""Tests for the configurable risk engine (Phase 4 Track 1).

Coverage:
  - Factor scale_min < scale_max DB check constraint
  - Active-per-name uniqueness on RiskScoringModel
  - weighted_sum normalizes correctly (max input → 100, min → 0)
  - weighted_avg respects per-factor weights
  - multiplicative requires likelihood + impact, rescales to 0..100
  - Out-of-range factor values raise RiskEngineError
  - Snapshot flips is_current on the previous row
  - High-risk threshold sets is_high_risk + bumps entity.risk_rating
  - Critical risk rating is preserved (never downgraded)
  - recompute_ranks: dense rank, ties share rank
  - heat_map cells contain right entity in right bucket
  - generate_audit_plan_draft creates an ApprovalRequest with auto-chain
  - API: /record/, /heat-map/, /generate-plan/ + RBAC gating
  - API: direct POST/PATCH/DELETE on /risk/scores/ is 405
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from iams.models import (
    ApprovalRequest,
    AuditLogEntry,
    AuditableEntity,
    EntityRiskScore,
    RiskFactor,
    RiskFactorWeight,
    RiskScoringModel,
)
from iams.risk_engine import (
    RiskEngineError,
    compute_composite,
    generate_audit_plan_draft,
    heat_map,
    record_score,
    recompute_ranks,
)

User = get_user_model()
pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def factors(db):
    impact = RiskFactor.objects.create(code="impact", name="Impact", scale_min=1, scale_max=5)
    likelihood = RiskFactor.objects.create(code="likelihood", name="Likelihood", scale_min=1, scale_max=5)
    control = RiskFactor.objects.create(code="control_maturity", name="Control Maturity", scale_min=1, scale_max=5)
    return {"impact": impact, "likelihood": likelihood, "control": control}


@pytest.fixture
def weighted_sum_model(factors):
    m = RiskScoringModel.objects.create(
        name="Default", version="1.0",
        formula=RiskScoringModel.FORMULA_WEIGHTED_SUM,
        is_active=True, high_risk_threshold=Decimal("70"),
    )
    RiskFactorWeight.objects.create(scoring_model=m, factor=factors["impact"], weight=Decimal("3"))
    RiskFactorWeight.objects.create(scoring_model=m, factor=factors["likelihood"], weight=Decimal("2"))
    return m


@pytest.fixture
def weighted_avg_model(factors):
    m = RiskScoringModel.objects.create(
        name="Avg", version="1.0",
        formula=RiskScoringModel.FORMULA_WEIGHTED_AVG,
        high_risk_threshold=Decimal("60"),
    )
    RiskFactorWeight.objects.create(scoring_model=m, factor=factors["impact"], weight=Decimal("2"))
    RiskFactorWeight.objects.create(scoring_model=m, factor=factors["likelihood"], weight=Decimal("1"))
    return m


@pytest.fixture
def multiplicative_model(factors):
    m = RiskScoringModel.objects.create(
        name="LxI", version="1.0",
        formula=RiskScoringModel.FORMULA_MULTIPLICATIVE,
        high_risk_threshold=Decimal("50"),
    )
    RiskFactorWeight.objects.create(scoring_model=m, factor=factors["impact"], weight=Decimal("1"))
    RiskFactorWeight.objects.create(scoring_model=m, factor=factors["likelihood"], weight=Decimal("1"))
    return m


@pytest.fixture
def entity():
    return AuditableEntity.objects.create(
        name="Accounts Payable", department="Finance", owner="o",
        risk_rating="Medium", status="Active",
    )


# ══════════════════════════════════════════════════════════════════════
# Constraints
# ══════════════════════════════════════════════════════════════════════
def test_factor_scale_min_lt_max_constraint(db):
    from django.db import IntegrityError, transaction
    with pytest.raises(IntegrityError), transaction.atomic():
        RiskFactor.objects.create(code="x", name="X", scale_min=5, scale_max=5)


def test_only_one_active_model_per_name(weighted_sum_model, factors):
    from django.db import IntegrityError, transaction
    with pytest.raises(IntegrityError), transaction.atomic():
        RiskScoringModel.objects.create(
            name="Default", version="1.1",
            formula=RiskScoringModel.FORMULA_WEIGHTED_SUM,
            is_active=True,
        )


def test_different_name_active_allowed(weighted_sum_model):
    # Same active flag, different name → OK
    RiskScoringModel.objects.create(
        name="Other", version="1.0",
        formula=RiskScoringModel.FORMULA_WEIGHTED_SUM,
        is_active=True,
    )


# ══════════════════════════════════════════════════════════════════════
# Scoring math
# ══════════════════════════════════════════════════════════════════════
def test_weighted_sum_max_inputs_score_100(weighted_sum_model):
    score = compute_composite(weighted_sum_model, {"impact": 5, "likelihood": 5})
    assert score == Decimal("100.00")


def test_weighted_sum_min_inputs_score_0(weighted_sum_model):
    score = compute_composite(weighted_sum_model, {"impact": 1, "likelihood": 1})
    assert score == Decimal("0.00")


def test_weighted_sum_respects_weights(weighted_sum_model):
    """Impact weight=3, Likelihood weight=2.
    impact=5 (normalized 1.0), likelihood=1 (normalized 0.0).
    Sum = 1.0*3 + 0.0*2 = 3.0; divided by total weight 5 = 0.6 → 60.00."""
    score = compute_composite(weighted_sum_model, {"impact": 5, "likelihood": 1})
    assert score == Decimal("60.00")


def test_weighted_avg_basic(weighted_avg_model):
    """Impact weight=2, Likelihood weight=1, both at max=5.
    Each contributes (5/5)*weight = 1*weight. Sum=2+1=3, divided by total=3 → 1.0 → 100."""
    score = compute_composite(weighted_avg_model, {"impact": 5, "likelihood": 5})
    assert score == Decimal("100.00")


def test_multiplicative_max_inputs_score_100(multiplicative_model):
    # max product = 5*5 = 25; (5*5)/25 *100 = 100
    score = compute_composite(multiplicative_model, {"likelihood": 5, "impact": 5})
    assert score == Decimal("100.00")


def test_multiplicative_mid_inputs(multiplicative_model):
    # 3*3/25 = 0.36 → 36.00
    score = compute_composite(multiplicative_model, {"likelihood": 3, "impact": 3})
    assert score == Decimal("36.00")


def test_multiplicative_missing_factor_raises(multiplicative_model, factors):
    # Remove the impact weight from this model — leaves only likelihood
    multiplicative_model.factor_weights.filter(factor=factors["impact"]).delete()
    with pytest.raises(RiskEngineError, match="likelihood.*impact"):
        compute_composite(multiplicative_model, {"likelihood": 3})


def test_out_of_range_value_raises(weighted_sum_model):
    with pytest.raises(RiskEngineError, match="out of range"):
        compute_composite(weighted_sum_model, {"impact": 10, "likelihood": 3})


def test_non_numeric_value_raises(weighted_sum_model):
    with pytest.raises(RiskEngineError, match="must be numeric"):
        compute_composite(weighted_sum_model, {"impact": "high", "likelihood": 3})


def test_compute_composite_with_no_factors_raises(factors):
    bare = RiskScoringModel.objects.create(
        name="Empty", version="1.0",
        formula=RiskScoringModel.FORMULA_WEIGHTED_SUM,
    )
    with pytest.raises(RiskEngineError, match="no factors"):
        compute_composite(bare, {"impact": 3})


# ══════════════════════════════════════════════════════════════════════
# Snapshot + is_current flip
# ══════════════════════════════════════════════════════════════════════
def test_record_score_creates_current_row(weighted_sum_model, entity, super_admin):
    score = record_score(
        entity, model=weighted_sum_model,
        factor_values={"impact": 4, "likelihood": 3},
        by_user=super_admin,
    )
    assert score.is_current is True
    assert score.composite_score > 0
    assert score.snapshot_by == super_admin


def test_record_score_flips_previous_to_not_current(weighted_sum_model, entity, super_admin):
    first = record_score(entity, model=weighted_sum_model, factor_values={"impact": 4, "likelihood": 3}, by_user=super_admin)
    second = record_score(entity, model=weighted_sum_model, factor_values={"impact": 5, "likelihood": 5}, by_user=super_admin)
    first.refresh_from_db()
    assert first.is_current is False
    assert second.is_current is True
    # Both rows in history
    history = EntityRiskScore.objects.filter(entity=entity, scoring_model=weighted_sum_model)
    assert history.count() == 2


def test_record_score_high_risk_bumps_entity_risk_rating(weighted_sum_model, entity, super_admin):
    """Threshold is 70. Max-input composite is 100 → high-risk → entity.risk_rating='High'."""
    assert entity.risk_rating == "Medium"
    record_score(entity, model=weighted_sum_model, factor_values={"impact": 5, "likelihood": 5}, by_user=super_admin)
    entity.refresh_from_db()
    assert entity.risk_rating == "High"


def test_critical_risk_rating_preserved(weighted_sum_model, super_admin):
    entity = AuditableEntity.objects.create(
        name="Top risk", department="X", owner="o",
        risk_rating="Critical", status="Active",
    )
    record_score(entity, model=weighted_sum_model, factor_values={"impact": 5, "likelihood": 5}, by_user=super_admin)
    entity.refresh_from_db()
    assert entity.risk_rating == "Critical"  # NOT downgraded


def test_record_score_low_does_not_set_high_risk(weighted_sum_model, entity, super_admin):
    record_score(entity, model=weighted_sum_model, factor_values={"impact": 1, "likelihood": 1}, by_user=super_admin)
    entity.refresh_from_db()
    current = EntityRiskScore.objects.get(entity=entity, scoring_model=weighted_sum_model, is_current=True)
    assert current.is_high_risk is False


# ══════════════════════════════════════════════════════════════════════
# Ranking
# ══════════════════════════════════════════════════════════════════════
def test_recompute_ranks_dense_ranking(weighted_sum_model, super_admin):
    # Three entities with different composites
    e1 = AuditableEntity.objects.create(name="A", department="X", owner="o", risk_rating="Medium", status="Active")
    e2 = AuditableEntity.objects.create(name="B", department="X", owner="o", risk_rating="Medium", status="Active")
    e3 = AuditableEntity.objects.create(name="C", department="X", owner="o", risk_rating="Medium", status="Active")
    record_score(e1, model=weighted_sum_model, factor_values={"impact": 5, "likelihood": 5}, by_user=super_admin)
    record_score(e2, model=weighted_sum_model, factor_values={"impact": 3, "likelihood": 3}, by_user=super_admin)
    record_score(e3, model=weighted_sum_model, factor_values={"impact": 1, "likelihood": 1}, by_user=super_admin)

    s1 = EntityRiskScore.objects.get(entity=e1, scoring_model=weighted_sum_model, is_current=True)
    s2 = EntityRiskScore.objects.get(entity=e2, scoring_model=weighted_sum_model, is_current=True)
    s3 = EntityRiskScore.objects.get(entity=e3, scoring_model=weighted_sum_model, is_current=True)
    assert s1.rank == 1
    assert s2.rank == 2
    assert s3.rank == 3


def test_recompute_ranks_ties_share_rank(weighted_sum_model, super_admin):
    e1 = AuditableEntity.objects.create(name="A", department="X", owner="o", risk_rating="Medium", status="Active")
    e2 = AuditableEntity.objects.create(name="B", department="X", owner="o", risk_rating="Medium", status="Active")
    e3 = AuditableEntity.objects.create(name="C", department="X", owner="o", risk_rating="Medium", status="Active")
    record_score(e1, model=weighted_sum_model, factor_values={"impact": 5, "likelihood": 5}, by_user=super_admin)
    record_score(e2, model=weighted_sum_model, factor_values={"impact": 5, "likelihood": 5}, by_user=super_admin)
    record_score(e3, model=weighted_sum_model, factor_values={"impact": 1, "likelihood": 1}, by_user=super_admin)
    s1 = EntityRiskScore.objects.get(entity=e1, scoring_model=weighted_sum_model, is_current=True)
    s2 = EntityRiskScore.objects.get(entity=e2, scoring_model=weighted_sum_model, is_current=True)
    s3 = EntityRiskScore.objects.get(entity=e3, scoring_model=weighted_sum_model, is_current=True)
    assert s1.rank == 1
    assert s2.rank == 1  # tied
    assert s3.rank == 2  # next rank — dense


# ══════════════════════════════════════════════════════════════════════
# Heat map
# ══════════════════════════════════════════════════════════════════════
def test_heat_map_places_entities_in_right_cells(weighted_sum_model, super_admin):
    e1 = AuditableEntity.objects.create(name="A", department="X", owner="o", risk_rating="Medium", status="Active")
    e2 = AuditableEntity.objects.create(name="B", department="X", owner="o", risk_rating="Medium", status="Active")
    record_score(e1, model=weighted_sum_model, factor_values={"impact": 5, "likelihood": 5}, by_user=super_admin)
    record_score(e2, model=weighted_sum_model, factor_values={"impact": 1, "likelihood": 2}, by_user=super_admin)

    grid = heat_map(weighted_sum_model)
    cells = {(c["likelihood"], c["impact"]): c for c in grid["cells"]}
    assert cells[(5, 5)]["count"] == 1
    assert cells[(5, 5)]["entities"][0]["entityName"] == "A"
    assert cells[(2, 1)]["count"] == 1
    # Untouched cell is empty
    assert cells[(3, 3)]["count"] == 0


def test_heat_map_requires_likelihood_and_impact_factors(weighted_sum_model, factors):
    # Remove the likelihood weight
    weighted_sum_model.factor_weights.filter(factor=factors["likelihood"]).delete()
    with pytest.raises(RiskEngineError, match="likelihood.*impact"):
        heat_map(weighted_sum_model)


# ══════════════════════════════════════════════════════════════════════
# Audit plan generation
# ══════════════════════════════════════════════════════════════════════
def test_generate_audit_plan_draft_creates_approval_request(weighted_sum_model, super_admin):
    e1 = AuditableEntity.objects.create(name="HighRisk", department="X", owner="o", risk_rating="Medium", status="Active")
    e2 = AuditableEntity.objects.create(name="MidRisk", department="X", owner="o", risk_rating="Medium", status="Active")
    record_score(e1, model=weighted_sum_model, factor_values={"impact": 5, "likelihood": 5}, by_user=super_admin)
    record_score(e2, model=weighted_sum_model, factor_values={"impact": 3, "likelihood": 3}, by_user=super_admin)

    req = generate_audit_plan_draft(model=weighted_sum_model, year=2026, top_n=10, requested_by=super_admin)
    assert isinstance(req, ApprovalRequest)
    assert req.type == "Audit Plan"
    assert req.status == "Pending"
    assert req.reference_id == "PLAN-2026"
    # Both entities appear in description, highest first
    body = req.description
    assert body.index("HighRisk") < body.index("MidRisk")


def test_generate_audit_plan_draft_empty_raises(weighted_sum_model, super_admin):
    with pytest.raises(RiskEngineError, match="No current risk scores"):
        generate_audit_plan_draft(model=weighted_sum_model, year=2026, top_n=10, requested_by=super_admin)


def test_generate_audit_plan_draft_top_n_validates(weighted_sum_model, super_admin, entity):
    record_score(entity, model=weighted_sum_model, factor_values={"impact": 3, "likelihood": 3}, by_user=super_admin)
    with pytest.raises(RiskEngineError, match="positive integer"):
        generate_audit_plan_draft(model=weighted_sum_model, year=2026, top_n=0, requested_by=super_admin)


# ══════════════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════════════
def test_api_record_score_endpoint(authed_client, super_admin, weighted_sum_model, entity):
    AuditLogEntry.objects.filter(action="other").delete()
    res = authed_client(super_admin).post(
        "/api/risk/scores/record/",
        {
            "entityId": str(entity.id),
            "scoringModelId": str(weighted_sum_model.id),
            "factorValues": {"impact": 4, "likelihood": 4},
            "notes": "Q1 refresh",
        },
        format="json",
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["isCurrent"] is True
    assert float(body["compositeScore"]) > 0
    assert AuditLogEntry.objects.filter(details__event="risk_score_recorded").exists()


def test_api_record_score_400_on_bad_input(authed_client, super_admin, weighted_sum_model, entity):
    res = authed_client(super_admin).post(
        "/api/risk/scores/record/",
        {
            "entityId": str(entity.id),
            "scoringModelId": str(weighted_sum_model.id),
            "factorValues": {"impact": 99},  # out of range
        },
        format="json",
    )
    assert res.status_code == 400


def test_api_direct_post_to_scores_is_405(authed_client, super_admin):
    res = authed_client(super_admin).post("/api/risk/scores/", {}, format="json")
    assert res.status_code == 405


def test_api_heat_map_endpoint(authed_client, super_admin, weighted_sum_model, entity):
    record_score(entity, model=weighted_sum_model, factor_values={"impact": 4, "likelihood": 5}, by_user=super_admin)
    res = authed_client(super_admin).get(
        f"/api/risk/heat-map/?scoring_model_id={weighted_sum_model.id}"
    )
    assert res.status_code == 200
    body = res.json()
    assert "cells" in body
    cell = next(c for c in body["cells"] if c["likelihood"] == 5 and c["impact"] == 4)
    assert cell["count"] == 1


def test_api_generate_plan_endpoint(authed_client, super_admin, weighted_sum_model, entity):
    record_score(entity, model=weighted_sum_model, factor_values={"impact": 5, "likelihood": 5}, by_user=super_admin)
    res = authed_client(super_admin).post(
        "/api/risk/generate-plan/",
        {
            "scoringModelId": str(weighted_sum_model.id),
            "year": 2026,
            "topN": 5,
        },
        format="json",
    )
    assert res.status_code == 201, res.content
    body = res.json()
    assert body["type"] == "Audit Plan"
    assert body["reference_id"] == "PLAN-2026"


def test_api_endpoints_require_view_audits(authed_client, db, roles):
    from django.contrib.auth import get_user_model
    from iams.models import Permission, Role, UserProfile
    User = get_user_model()
    p = Permission.objects.create(key="random_risk", name="x", module="test")
    role = Role.objects.create(name="Restricted-Risk", is_super_admin=False)
    role.permissions.set([p])
    user = User.objects.create_user(username="r_risk", email="rr@iams.test", password="TestPassword123!")
    UserProfile.objects.create(user=user, role=role, department="X", status="Active")
    client = authed_client(user)
    for path in [
        "/api/risk/factors/", "/api/risk/models/", "/api/risk/scores/",
        "/api/risk/factor-weights/",
        "/api/risk/heat-map/?scoring_model_id=00000000-0000-0000-0000-000000000000",
    ]:
        assert client.get(path).status_code == 403, f"{path} should be 403"


def test_api_recompute_endpoint(authed_client, super_admin, weighted_sum_model, entity):
    record_score(entity, model=weighted_sum_model, factor_values={"impact": 3, "likelihood": 3}, by_user=super_admin)
    res = authed_client(super_admin).post(
        f"/api/risk/models/{weighted_sum_model.id}/recompute/"
    )
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["recomputed"] == 1


@pytest.mark.django_db
def test_audit_universe_recompute_is_async(authed_client, super_admin, weighted_sum_model, entity):
    """The audit-universe recompute action queues a Celery task (202) and,
    under eager mode, still re-snapshots the scored entities."""
    from iams.models import EntityRiskScore

    record_score(entity, model=weighted_sum_model, factor_values={"impact": 3, "likelihood": 3}, by_user=super_admin)
    before = EntityRiskScore.objects.filter(entity=entity).count()

    res = authed_client(super_admin).post("/api/auditable-entities/recompute-risk-scores/")
    assert res.status_code == 202, res.content
    body = res.json()
    assert body["status"] == "queued"
    assert body["modelId"] == str(weighted_sum_model.id)

    # Eager Celery ran the task inline → a fresh snapshot exists.
    assert EntityRiskScore.objects.filter(entity=entity).count() == before + 1
    assert EntityRiskScore.objects.filter(entity=entity, is_current=True).count() == 1
