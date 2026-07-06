"""Tests for the risk-domain correctness + governance upgrades.

Covers:
  - A1: EntityRisk updates are audit-logged (mixin no longer bypassed)
  - A3: residual > inherent is rejected (serializer + DB CheckConstraint)
  - D1: RiskHistoryEntry is append-only
  - D2: a manual rating override writes a RiskHistoryEntry
  - B1: engine scoring routes through the single rating authority and
        de-escalates a prior engine-driven High when a lower snapshot lands
  - B7: each EntityRiskScore freezes a model_snapshot for reproducibility
  - B8: publish → "Risk Model Change" approval → activation on approval;
        direct isActive writes are rejected
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction

from iams.models import (
    ApprovalRequest,
    ApprovalStep,
    AuditableEntity,
    AuditLogEntry,
    EntityRisk,
    RiskFactor,
    RiskFactorWeight,
    RiskHistoryEntry,
    RiskScoringModel,
)
from iams.risk_engine import record_score
from iams.workflows import advance_on_approve

User = get_user_model()
pytestmark = pytest.mark.django_db


# ── Fixtures ───────────────────────────────────────────────────────────
@pytest.fixture
def factors(db):
    impact = RiskFactor.objects.create(code="impact", name="Impact", scale_min=1, scale_max=5)
    likelihood = RiskFactor.objects.create(code="likelihood", name="Likelihood", scale_min=1, scale_max=5)
    return {"impact": impact, "likelihood": likelihood}


@pytest.fixture
def active_model(factors):
    m = RiskScoringModel.objects.create(
        name="Default", version="1.0",
        formula=RiskScoringModel.FORMULA_WEIGHTED_SUM,
        is_active=True, high_risk_threshold=Decimal("70"),
    )
    RiskFactorWeight.objects.create(scoring_model=m, factor=factors["impact"], weight=Decimal("3"))
    RiskFactorWeight.objects.create(scoring_model=m, factor=factors["likelihood"], weight=Decimal("2"))
    return m


@pytest.fixture
def entity(db):
    return AuditableEntity.objects.create(
        name="Accounts Payable", department="Finance", owner="o",
        risk_rating="Medium", status="Active",
    )


# ── A1: EntityRisk update is audit-logged ──────────────────────────────
def test_entity_risk_update_writes_audit_log(authed_client, super_admin, entity):
    client = authed_client(super_admin)
    created = client.post(
        "/api/entity-risks/",
        {"entityId": str(entity.id), "title": "Vendor fraud",
         "inherentLikelihood": 3, "inherentImpact": 3},
        format="json",
    )
    assert created.status_code == 201, created.content
    risk_id = created.json()["id"]
    ct_before = AuditLogEntry.objects.filter(action=AuditLogEntry.ACTION_UPDATE).count()

    resp = client.patch(f"/api/entity-risks/{risk_id}/", {"status": "Mitigated"}, format="json")
    assert resp.status_code == 200, resp.content
    ct_after = AuditLogEntry.objects.filter(action=AuditLogEntry.ACTION_UPDATE).count()
    assert ct_after == ct_before + 1


# ── A3: residual cannot exceed inherent ────────────────────────────────
def test_residual_cannot_exceed_inherent_via_api(authed_client, super_admin, entity):
    client = authed_client(super_admin)
    resp = client.post(
        "/api/entity-risks/",
        {"entityId": str(entity.id), "title": "x",
         "inherentLikelihood": 2, "inherentImpact": 2,
         "residualLikelihood": 4, "residualImpact": 2},
        format="json",
    )
    assert resp.status_code == 400
    assert "residualLikelihood" in resp.json()


def test_residual_le_inherent_db_constraint(entity):
    with pytest.raises(IntegrityError), transaction.atomic():
        EntityRisk.objects.create(
            entity=entity, title="raw", inherent_likelihood=2, inherent_impact=2,
            residual_likelihood=5, residual_impact=2,
        )


# ── D1: RiskHistoryEntry append-only ───────────────────────────────────
def test_risk_history_is_append_only(entity):
    row = RiskHistoryEntry.objects.create(
        entity=entity.name, entity_ref=entity, date="2026-01-01",
        previous_rating="Low", current_rating="High", reason="test",
    )
    row.current_rating = "Critical"
    with pytest.raises(PermissionError):
        row.save()
    with pytest.raises(PermissionError):
        row.delete()


# ── D2: manual override writes RiskHistoryEntry ────────────────────────
def test_manual_rating_override_writes_history(authed_client, super_admin, entity):
    client = authed_client(super_admin)
    resp = client.patch(
        f"/api/auditable-entities/{entity.id}/",
        {"riskRating": "Critical", "riskRatingIsOverridden": True, "version": entity.version},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    hist = RiskHistoryEntry.objects.filter(entity_ref=entity, reason="Manual rating override")
    assert hist.count() == 1
    assert hist.first().current_rating == "Critical"


# ── B1: engine de-escalation via the single authority ──────────────────
def test_engine_rating_deescalates_on_lower_snapshot(active_model, entity, super_admin):
    # High composite → entity escalates to High.
    record_score(entity, model=active_model, factor_values={"impact": 5, "likelihood": 5}, by_user=super_admin)
    entity.refresh_from_db()
    assert entity.risk_rating == "High"
    # A subsequent low snapshot clears the engine high-risk flag → de-escalates.
    record_score(entity, model=active_model, factor_values={"impact": 1, "likelihood": 1}, by_user=super_admin)
    entity.refresh_from_db()
    assert entity.risk_rating != "High"
    # And the change is captured in the immutable history.
    assert RiskHistoryEntry.objects.filter(entity_ref=entity).exists()


def test_inactive_model_score_does_not_escalate(factors, entity, super_admin):
    inactive = RiskScoringModel.objects.create(
        name="Experimental", version="1.0",
        formula=RiskScoringModel.FORMULA_WEIGHTED_SUM,
        is_active=False, high_risk_threshold=Decimal("70"),
    )
    RiskFactorWeight.objects.create(scoring_model=inactive, factor=factors["impact"], weight=Decimal("1"))
    RiskFactorWeight.objects.create(scoring_model=inactive, factor=factors["likelihood"], weight=Decimal("1"))
    record_score(entity, model=inactive, factor_values={"impact": 5, "likelihood": 5}, by_user=super_admin)
    entity.refresh_from_db()
    assert entity.risk_rating == "Medium"  # not escalated by a non-active model


# ── B7: reproducible model snapshot ────────────────────────────────────
def test_score_freezes_model_snapshot(active_model, entity, super_admin):
    score = record_score(entity, model=active_model, factor_values={"impact": 4, "likelihood": 3}, by_user=super_admin)
    snap = score.model_snapshot
    assert snap["formula"] == RiskScoringModel.FORMULA_WEIGHTED_SUM
    assert Decimal(snap["highRiskThreshold"]) == Decimal("70")
    codes = {f["code"] for f in snap["factors"]}
    assert codes == {"impact", "likelihood"}


# ── B8: governance-gated activation ────────────────────────────────────
def test_direct_isactive_write_is_ignored(authed_client, super_admin, factors):
    draft = RiskScoringModel.objects.create(
        name="Draft", version="1.0", formula=RiskScoringModel.FORMULA_WEIGHTED_SUM,
        is_active=False,
    )
    resp = authed_client(super_admin).patch(
        f"/api/risk/models/{draft.id}/", {"isActive": True}, format="json",
    )
    assert resp.status_code == 200, resp.content
    draft.refresh_from_db()
    assert draft.is_active is False  # activation cannot be forced through the serializer


def test_publish_creates_approval_and_activation_on_approval(authed_client, super_admin, factors):
    draft = RiskScoringModel.objects.create(
        name="Draft", version="1.0", formula=RiskScoringModel.FORMULA_WEIGHTED_SUM,
        is_active=False,
    )
    RiskFactorWeight.objects.create(scoring_model=draft, factor=factors["impact"], weight=Decimal("1"))

    resp = authed_client(super_admin).post(f"/api/risk/models/{draft.id}/publish/")
    assert resp.status_code == 201, resp.content
    req = ApprovalRequest.objects.get(reference_id=str(draft.id), type="Risk Model Change")
    draft.refresh_from_db()
    assert draft.is_active is False  # still pending approval

    # Drive the approval to completion → activation side-effect fires.
    ApprovalStep.objects.create(
        request=req, order=0, role="Audit Manager", approver=super_admin.email, status="Pending",
    )
    req.current_step = 0
    req.save(update_fields=["current_step"])
    advance_on_approve(req, by_user=super_admin)

    draft.refresh_from_db()
    assert draft.is_active is True


def test_publish_deactivates_the_previously_active_model(authed_client, super_admin, factors, active_model):
    draft = RiskScoringModel.objects.create(
        name="NewModel", version="1.0", formula=RiskScoringModel.FORMULA_WEIGHTED_SUM,
        is_active=False,
    )
    RiskFactorWeight.objects.create(scoring_model=draft, factor=factors["impact"], weight=Decimal("1"))
    publish = authed_client(super_admin).post(f"/api/risk/models/{draft.id}/publish/")
    assert publish.status_code == 201, publish.content
    req = ApprovalRequest.objects.get(reference_id=str(draft.id), type="Risk Model Change")
    ApprovalStep.objects.create(
        request=req, order=0, role="Audit Manager", approver=super_admin.email, status="Pending",
    )
    advance_on_approve(req, by_user=super_admin)

    draft.refresh_from_db()
    active_model.refresh_from_db()
    assert draft.is_active is True
    assert active_model.is_active is False
    assert RiskScoringModel.objects.filter(is_active=True).count() == 1
