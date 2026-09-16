"""Tests for the Audit Universe v2 API surface.

Covers the pieces added in PR 1 (see docs/AUDIT-UNIVERSE-FORM-SPEC.md):

  - the new v2 columns round-trip through the entity API
  - StrategicObjective / KeySystem lookups, with objective coverage counts
  - the configurable materiality metric registry and its applies_to narrowing
  - materiality values, and the denormalised sort cache they maintain
  - assurance coverage, including the reliance-needs-a-rationale rule at both
    the serializer and the database level
  - derived helpers: total effort, months since last audit, suggested frequency
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from rest_framework import status

from iams.materiality import build_materiality_cache, refresh_materiality_cache
from iams.models import (
    AssuranceCoverage,
    AuditableEntity,
    AuditFrequencyChoices,
    EntityMaterialityValue,
    KeySystem,
    MaterialityMetricDefinition,
    RiskRatingChoices,
    StrategicObjective,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def sa_client(super_admin, authed_client):
    return authed_client(super_admin)


@pytest.fixture
def matrix_user(db):
    """Build a user holding one of the nine canonical matrix roles.

    The shared ``roles`` fixture still seeds the legacy six-role names; the
    RBAC questions here are specifically about the matrix roles and the exact
    levels they hold on ``audit_universe`` and ``risk_assessment``, so the cells
    come straight from ROLE_MATRIX rather than from a legacy key set.
    """
    from django.contrib.auth import get_user_model

    from iams.models import Role, RoleModuleAccess, UserProfile
    from iams.rbac_matrix import ROLE_MATRIX
    from iams.tests._rbac import ensure_modules

    User = get_user_model()
    modules = ensure_modules()

    def _make(role_name: str):
        cells = ROLE_MATRIX[role_name]
        role, _ = Role.objects.get_or_create(
            name=role_name,
            defaults={"is_super_admin": role_name == "System administrator"},
        )
        for module_key, (level, scoped) in cells.items():
            module = modules.get(module_key)
            if module is None:
                continue
            RoleModuleAccess.objects.update_or_create(
                role=role, module=module,
                defaults={"level": level, "scoped": scoped},
            )
        slug = role_name.lower().replace(" ", "_").replace("/", "_")
        user = User.objects.create_user(
            username=f"matrix_{slug}",
            email=f"matrix_{slug}@iams.test",
            password="MatrixPass123!",
        )
        UserProfile.objects.create(
            user=user, role=role, department="Audit", status="Active",
        )
        return user

    return _make


@pytest.fixture
def entity(db) -> AuditableEntity:
    return AuditableEntity.objects.create(
        name="Claims handling",
        entity_type="Process",
        universe_category="Operations",
        status="Active",
    )


@pytest.fixture
def revenue_metric(db) -> MaterialityMetricDefinition:
    return MaterialityMetricDefinition.objects.create(
        code="annual_revenue", label="Annual revenue", unit="currency",
        currency="USD", display_order=1,
    )


# ══════════════════════════════════════════════════════════════════════
# New columns on the entity
# ══════════════════════════════════════════════════════════════════════
def test_v2_mandate_fields_round_trip(sa_client, entity):
    """Objectives, scope and resources persist and come back out.

    These three are what the IIA practice guide asks to be "clearly defined"
    for every auditable unit, so a silent drop here is the whole point of the
    v2 work going missing.
    """
    resp = sa_client.patch(
        f"/api/auditable-entities/{entity.id}/",
        {
            "version": entity.version,
            "code": "OPS-0042",
            "universeCategory": "Operations",
            "auditObjectives": "Establish that claims are settled within policy terms.",
            "scopeInclusions": "First-notification-of-loss through settlement.",
            "scopeExclusions": "Reinsurance recoveries.",
            "frequencySource": "Mandated",
            "mandateReference": "Insurance Ordinance s.42",
            "estimatedIaDays": "18.00",
            "estimatedCosourceDays": "4.50",
            "requiredSkills": ["actuarial", "data_analytics"],
            "applicableFrameworks": ["IFRS 17", "AML/CFT"],
            "isFraudRiskRelevant": True,
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.data

    entity.refresh_from_db()
    assert entity.code == "OPS-0042"
    assert entity.audit_objectives.startswith("Establish that claims")
    assert entity.scope_exclusions == "Reinsurance recoveries."
    assert entity.frequency_source == "Mandated"
    assert entity.mandate_reference == "Insurance Ordinance s.42"
    assert entity.required_skills == ["actuarial", "data_analytics"]
    assert entity.applicable_frameworks == ["IFRS 17", "AML/CFT"]
    assert entity.is_fraud_risk_relevant is True


def test_total_estimated_days_sums_the_split(entity):
    """Total effort is IA + co-source once either is set."""
    entity.estimated_ia_days = Decimal("18.00")
    entity.estimated_cosource_days = Decimal("4.50")
    assert entity.total_estimated_days == Decimal("22.50")


def test_total_estimated_days_falls_back_to_the_legacy_column(entity):
    """Entities not yet migrated to the split keep reporting their old figure.

    ``estimated_man_days`` stays populated for one release; without this
    fallback every pre-v2 entity would report no effort at all and drop out of
    capacity-based planning.
    """
    entity.estimated_man_days = Decimal("12.00")
    assert entity.total_estimated_days == Decimal("12.00")


def test_months_since_last_audit(entity):
    assert entity.months_since_last_audit is None
    entity.last_audit_date = date.today() - timedelta(days=400)
    assert entity.months_since_last_audit == 13


@pytest.mark.parametrize(
    "rating,expected",
    [
        (RiskRatingChoices.CRITICAL, AuditFrequencyChoices.ANNUAL),
        (RiskRatingChoices.HIGH, AuditFrequencyChoices.ANNUAL),
        (RiskRatingChoices.MEDIUM, AuditFrequencyChoices.BIENNIAL),
        (RiskRatingChoices.LOW, AuditFrequencyChoices.TRIENNIAL),
    ],
)
def test_suggested_frequency_follows_the_iia_bands(entity, rating, expected):
    """High risk at least annually, moderate 19-24 months, low 25-36 months."""
    entity.risk_rating = rating
    assert entity.suggested_audit_frequency() == expected


# ══════════════════════════════════════════════════════════════════════
# Lookups
# ══════════════════════════════════════════════════════════════════════
def test_strategic_objective_reports_coverage_count(sa_client, entity):
    """entityCount is how an uncovered objective becomes visible."""
    covered = StrategicObjective.objects.create(code="OBJ-1", title="Grow retail book")
    StrategicObjective.objects.create(code="OBJ-2", title="Exit legacy lines")
    entity.strategic_objectives.add(covered)

    resp = sa_client.get("/api/strategic-objectives/")
    assert resp.status_code == status.HTTP_200_OK
    by_code = {row["code"]: row for row in resp.data["results"]}
    assert by_code["OBJ-1"]["entityCount"] == 1
    assert by_code["OBJ-2"]["entityCount"] == 0


def test_key_system_active_only_filter(sa_client):
    KeySystem.objects.create(name="Guidewire ClaimCenter", criticality="Critical")
    KeySystem.objects.create(name="Retired mainframe", is_active=False)

    resp = sa_client.get("/api/key-systems/?activeOnly=true")
    names = [row["name"] for row in resp.data["results"]]
    assert names == ["Guidewire ClaimCenter"]


# ══════════════════════════════════════════════════════════════════════
# Materiality registry
# ══════════════════════════════════════════════════════════════════════
def test_metric_registry_applies_to_narrowing(sa_client, revenue_metric):
    """A scoped metric is offered only where it belongs; unscoped ones always.

    ``applies_to`` is an opt-in narrowing — an empty list means "offer this
    everywhere" — so a filtered request must still return the general metrics.
    """
    MaterialityMetricDefinition.objects.create(
        code="gross_written_premium", label="Gross written premium",
        unit="currency", currency="USD",
        applies_to=["Underwriting"], display_order=10,
    )

    resp = sa_client.get("/api/materiality-metrics/?universeCategory=Operations")
    codes = {row["code"] for row in resp.data["results"]}
    assert "annual_revenue" in codes
    assert "gross_written_premium" not in codes

    resp = sa_client.get("/api/materiality-metrics/?universeCategory=Underwriting")
    codes = {row["code"] for row in resp.data["results"]}
    assert {"annual_revenue", "gross_written_premium"} <= codes


def test_currency_metric_requires_a_currency(sa_client):
    """An amount without a currency is an ambiguous figure."""
    resp = sa_client.post(
        "/api/materiality-metrics/",
        {"code": "loose_amount", "label": "Loose amount", "unit": "currency"},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "currency" in resp.data


def test_metric_registry_writes_need_administration_rights(auditor_user, authed_client, revenue_metric):
    """Reading the registry is part of the job; changing it is configuration.

    Editing a definition changes what every entity in the organization is
    asked for, so it sits behind the administration gate rather than
    audit_universe edit.
    """
    client = authed_client(auditor_user)

    assert client.get("/api/materiality-metrics/").status_code == status.HTTP_200_OK

    resp = client.patch(
        f"/api/materiality-metrics/{revenue_metric.id}/",
        {"label": "Turnover"},
        format="json",
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ══════════════════════════════════════════════════════════════════════
# Materiality values + sort cache
# ══════════════════════════════════════════════════════════════════════
def test_posting_a_value_refreshes_the_sort_cache(sa_client, entity, revenue_metric):
    resp = sa_client.post(
        "/api/entity-materiality/",
        {
            "entityId": str(entity.id),
            "definitionId": str(revenue_metric.id),
            "value": "4100000.00",
            "asOf": "2026-03-31",
            "source": "GL extract FY26",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.data

    entity.refresh_from_db()
    assert entity.materiality_cache == {"annual_revenue": 4100000.0}


def test_cache_takes_the_most_recent_period(entity, revenue_metric):
    """Two periods for one metric: the newest wins in the cache."""
    EntityMaterialityValue.objects.create(
        entity=entity, definition=revenue_metric,
        value=Decimal("3000000"), as_of=date(2025, 3, 31),
    )
    EntityMaterialityValue.objects.create(
        entity=entity, definition=revenue_metric,
        value=Decimal("4100000"), as_of=date(2026, 3, 31),
    )
    assert build_materiality_cache(entity) == {"annual_revenue": 4100000.0}


def test_cache_refresh_does_not_bump_version(entity, revenue_metric):
    """Refreshing a derived cache is not a user edit.

    If it bumped ``version`` it would make a concurrent PATCH fail its
    optimistic-locking check with a 409 that the user did nothing to earn.
    """
    before = entity.version
    EntityMaterialityValue.objects.create(
        entity=entity, definition=revenue_metric,
        value=Decimal("1"), as_of=date(2026, 3, 31),
    )
    refresh_materiality_cache(entity)

    entity.refresh_from_db()
    assert entity.version == before
    assert entity.materiality_cache == {"annual_revenue": 1.0}


def test_one_value_per_metric_per_period(entity, revenue_metric):
    EntityMaterialityValue.objects.create(
        entity=entity, definition=revenue_metric,
        value=Decimal("1"), as_of=date(2026, 3, 31),
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        EntityMaterialityValue.objects.create(
            entity=entity, definition=revenue_metric,
            value=Decimal("2"), as_of=date(2026, 3, 31),
        )


# ══════════════════════════════════════════════════════════════════════
# Assurance coverage (Standard 9.5)
# ══════════════════════════════════════════════════════════════════════
def test_reliance_without_rationale_is_rejected(sa_client, entity):
    resp = sa_client.post(
        "/api/assurance-coverage/",
        {
            "entityId": str(entity.id),
            "providerName": "Group Compliance",
            "providerType": "second_line",
            "relianceLevel": "partial",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "relianceRationale" in resp.data


def test_reliance_with_rationale_is_accepted(sa_client, entity):
    resp = sa_client.post(
        "/api/assurance-coverage/",
        {
            "entityId": str(entity.id),
            "providerName": "Group Compliance",
            "providerType": "second_line",
            "scope": "Sanctions screening controls",
            "lastReviewDate": "2026-02-10",
            "relianceLevel": "partial",
            "relianceRationale": "Methodology reviewed by IA in Q4 2025; testing re-performed on a sample.",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.data
    assert AssuranceCoverage.objects.filter(entity=entity).count() == 1


def test_future_last_review_date_is_rejected(sa_client, entity):
    """A future 'last review' would feed the recency factor a false signal."""
    resp = sa_client.post(
        "/api/assurance-coverage/",
        {
            "entityId": str(entity.id),
            "providerName": "External audit",
            "providerType": "external_audit",
            "lastReviewDate": str(date.today() + timedelta(days=30)),
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "lastReviewDate" in resp.data


def test_reliance_rule_is_enforced_by_the_database_too(entity):
    """The serializer is not the only writer — admin and imports write here."""
    with pytest.raises(IntegrityError), transaction.atomic():
        AssuranceCoverage.objects.create(
            entity=entity,
            provider_name="Regulator",
            provider_type="regulator",
            reliance_level="full",
            reliance_rationale="",
        )


# ══════════════════════════════════════════════════════════════════════
# Filters
# ══════════════════════════════════════════════════════════════════════
def test_framework_and_skill_filters(sa_client, entity):
    """JSON-list columns filter correctly on both Postgres and SQLite."""
    entity.applicable_frameworks = ["IFRS 17", "AML/CFT"]
    entity.required_skills = ["actuarial"]
    entity.save()
    AuditableEntity.objects.create(
        name="IT general controls", entity_type="Process",
        applicable_frameworks=["SOX"], required_skills=["it_general_controls"],
    )

    resp = sa_client.get("/api/auditable-entities/?applicableFramework=IFRS 17")
    assert [r["name"] for r in resp.data["results"]] == ["Claims handling"]

    resp = sa_client.get("/api/auditable-entities/?requiredSkill=it_general_controls")
    assert [r["name"] for r in resp.data["results"]] == ["IT general controls"]


def test_coverage_gap_filters(sa_client, entity):
    """The tiles that tell a team what to finish before planning season."""
    complete = AuditableEntity.objects.create(
        name="Underwriting", entity_type="Process",
        audit_objectives="Establish pricing discipline.",
        scope_inclusions="Quote through bind.",
        estimated_ia_days=Decimal("10"),
    )

    resp = sa_client.get("/api/auditable-entities/?withoutObjectives=true")
    names = {r["name"] for r in resp.data["results"]}
    assert entity.name in names and complete.name not in names

    resp = sa_client.get("/api/auditable-entities/?withoutEffortEstimate=true")
    names = {r["name"] for r in resp.data["results"]}
    assert entity.name in names and complete.name not in names


def test_legacy_man_days_counts_as_an_effort_estimate(sa_client, entity):
    """A pre-v2 entity is not reported as missing an estimate it already has."""
    entity.estimated_man_days = Decimal("8")
    entity.save()

    resp = sa_client.get("/api/auditable-entities/?withoutEffortEstimate=true")
    assert entity.name not in {r["name"] for r in resp.data["results"]}


def test_universe_category_filter_accepts_a_csv(sa_client, entity):
    AuditableEntity.objects.create(
        name="Board reporting", entity_type="Process", universe_category="Governance",
    )
    AuditableEntity.objects.create(
        name="Payroll", entity_type="Process", universe_category="Support",
    )

    resp = sa_client.get("/api/auditable-entities/?universeCategory=Operations,Governance")
    assert {r["name"] for r in resp.data["results"]} == {"Claims handling", "Board reporting"}


# ══════════════════════════════════════════════════════════════════════
# Audit trail
# ══════════════════════════════════════════════════════════════════════
def test_v2_field_changes_land_in_the_revision_diff(sa_client, entity):
    """Objectives and effort are exactly what a QA reviewer asks about."""
    from iams.models import AuditableEntityRevision

    sa_client.patch(
        f"/api/auditable-entities/{entity.id}/",
        {
            "version": entity.version,
            "auditObjectives": "Establish that claims are settled within policy terms.",
            "estimatedIaDays": "18.00",
        },
        format="json",
    )

    revision = AuditableEntityRevision.objects.filter(entity=entity).order_by("-version").first()
    assert revision is not None
    assert "audit_objectives" in revision.changes
    assert revision.changes["audit_objectives"]["to"].startswith("Establish that claims")
    assert "estimated_ia_days" in revision.changes


# ══════════════════════════════════════════════════════════════════════
# Readiness
# ══════════════════════════════════════════════════════════════════════
@pytest.fixture
def active_model(db):
    from iams.models import RiskFactor, RiskFactorWeight, RiskScoringModel

    model = RiskScoringModel.objects.create(
        name="Active", version="1.0",
        formula=RiskScoringModel.FORMULA_IMPACT_LIKELIHOOD, is_active=True,
    )
    for code, group, weight in (
        ("exposure", "impact", 100), ("controls", "likelihood", 100),
    ):
        factor = RiskFactor.objects.create(
            code=code, name=code.title(), group=group, scale_min=1, scale_max=5,
        )
        RiskFactorWeight.objects.create(scoring_model=model, factor=factor, weight=weight)
    return model


def _make_assessed(entity, user, metric, model):
    """Satisfy every readiness criterion."""
    from iams.risk_engine import record_score

    entity.primary_owner = user
    entity.audit_objectives = "Establish that claims are settled within policy terms."
    entity.scope_inclusions = "FNOL through settlement."
    entity.frequency_source = "RiskBased"
    entity.estimated_ia_days = Decimal("18")
    entity.save()
    EntityMaterialityValue.objects.create(
        entity=entity, definition=metric, value=Decimal("1"), as_of=date.today(),
    )
    refresh_materiality_cache(entity)
    entity.refresh_from_db()
    record_score(entity, model=model, factor_values={"exposure": 4, "controls": 4})
    return entity


def test_readiness_starts_in_draft(sa_client, entity):
    """A brand-new entity scores zero.

    No criterion may be satisfiable by a model default, or an empty record
    would advertise progress nobody made.
    """
    from iams import readiness

    result = readiness.compute(entity)
    assert result["score"] == 0
    assert result["band"] == readiness.BAND_DRAFT
    assert result["isPlanEligible"] is False
    assert "hasObjectives" in result["missing"]


def test_a_complete_entity_reaches_assessed(entity, super_admin, revenue_metric, active_model):
    from iams import readiness

    _make_assessed(entity, super_admin, revenue_metric, active_model)
    entity.refresh_from_db()

    result = readiness.compute(entity)
    assert result["score"] == readiness.MAX_SCORE
    assert result["band"] == readiness.BAND_ASSESSED
    assert result["isPlanEligible"] is True
    assert result["missing"] == []


def test_a_score_from_an_inactive_model_does_not_count(entity, active_model):
    """A snapshot against a superseded model is history, not an assessment.

    Counting it would let the plan quietly rest on last year's weights.
    """
    from iams import readiness
    from iams.models import RiskScoringModel
    from iams.risk_engine import record_score

    def scored(e):
        by_key = {c["key"]: c for c in readiness.compute(e)["criteria"]}
        return by_key["hasCurrentRiskScore"]["met"]

    record_score(entity, model=active_model, factor_values={"exposure": 3, "controls": 3})
    assert scored(entity) is True

    RiskScoringModel.objects.filter(pk=active_model.pk).update(is_active=False)
    entity.refresh_from_db()
    assert scored(entity) is False


def test_readiness_endpoint_returns_the_breakdown(sa_client, entity):
    """The breakdown is what makes the number actionable."""
    resp = sa_client.get(f"/api/auditable-entities/{entity.id}/readiness/")

    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["band"] == "Draft"
    keys = {c["key"] for c in resp.data["criteria"]}
    assert "hasEffortEstimate" in keys
    assert all("hint" in c for c in resp.data["criteria"])


def test_readiness_appears_on_the_list_projection(sa_client, entity):
    resp = sa_client.get("/api/auditable-entities/")
    row = next(r for r in resp.data["results"] if r["name"] == entity.name)
    assert row["readinessScore"] == 0
    assert row["readinessBand"] == "Draft"


def test_list_readiness_does_not_issue_a_query_per_row(
    sa_client, django_assert_max_num_queries, revenue_metric, active_model, super_admin,
):
    """Readiness on the register must not be N+1.

    The active-model score lookup is prefetched into
    ``_prefetched_current_scores``; without that this grows a query per entity.
    """
    from iams.risk_engine import record_score

    for i in range(12):
        e = AuditableEntity.objects.create(name=f"Entity {i}", entity_type="Process")
        record_score(e, model=active_model, factor_values={"exposure": 3, "controls": 3})

    with django_assert_max_num_queries(15):
        resp = sa_client.get("/api/auditable-entities/?page_size=50")
    assert resp.status_code == status.HTTP_200_OK
    assert all(r["readinessScore"] > 0 for r in resp.data["results"])


def test_coverage_reports_the_v2_gaps(sa_client, entity):
    resp = sa_client.get("/api/auditable-entities/coverage/")

    assert resp.status_code == status.HTTP_200_OK
    assert resp.data["withoutObjectives"] == 1
    assert resp.data["withoutScope"] == 1
    assert resp.data["withoutEffortEstimate"] == 1
    assert resp.data["withoutCurrentFactorScore"] == 1


# ══════════════════════════════════════════════════════════════════════
# Rating override
# ══════════════════════════════════════════════════════════════════════
def test_rating_cannot_be_written_through_the_entity_api(sa_client, entity):
    """The hole the v2 work exists to close.

    The frontend no longer sends riskRating, but bulk import and any external
    client still could. Locking it at the serializer is what actually shuts it.
    """
    resp = sa_client.patch(
        f"/api/auditable-entities/{entity.id}/",
        {"riskRating": "Critical", "version": entity.version},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK
    entity.refresh_from_db()
    assert entity.risk_rating == "Medium"
    assert entity.risk_rating_is_overridden is False


def test_override_requires_a_real_rationale(sa_client, entity):
    """"n/a" and "per CAE" are exactly what this is here to stop."""
    resp = sa_client.post(
        f"/api/auditable-entities/{entity.id}/override-rating/",
        {"rating": "Critical", "rationale": "n/a"},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "rationale" in resp.data
    entity.refresh_from_db()
    assert entity.risk_rating == "Medium"


def test_override_rejects_an_unknown_rating(sa_client, entity):
    resp = sa_client.post(
        f"/api/auditable-entities/{entity.id}/override-rating/",
        {"rating": "Extreme", "rationale": "Escalated after the Q2 incident review."},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "rating" in resp.data


def test_override_writes_history_and_a_revision(sa_client, entity):
    from iams.models import AuditableEntityRevision, RiskHistoryEntry

    resp = sa_client.post(
        f"/api/auditable-entities/{entity.id}/override-rating/",
        {
            "rating": "Critical",
            "rationale": "Escalated by the audit committee after the Q2 incident.",
            "expiresOn": "2027-06-30",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.data

    entity.refresh_from_db()
    assert entity.risk_rating == "Critical"
    assert entity.risk_rating_is_overridden is True

    history = RiskHistoryEntry.objects.get(entity_ref=entity)
    assert history.previous_rating == "Medium"
    assert history.current_rating == "Critical"
    assert "audit committee" in history.reason
    assert "2027-06-30" in history.reason

    revision = AuditableEntityRevision.objects.filter(entity=entity).order_by("-version").first()
    assert "audit committee" in revision.comment


def test_releasing_an_override_that_is_not_set_is_a_conflict(sa_client, entity):
    resp = sa_client.delete(f"/api/auditable-entities/{entity.id}/override-rating/")
    assert resp.status_code == status.HTTP_409_CONFLICT


# ── RBAC: the trap from the spec, asserted both ways ──────────────────
def test_senior_auditor_can_score_but_cannot_override(
    authed_client, matrix_user, entity, active_model,
):
    """Senior auditor holds risk_assessment *edit* to enter factor scores.

    Entering an assessment and overruling one are different acts, so the
    override sits at approve. If they shared a gate, anyone who can score could
    overrule the score.
    """
    client = authed_client(matrix_user("Senior auditor"))

    scored = client.put(
        f"/api/auditable-entities/{entity.id}/risk-factors/",
        {"factorValues": {"exposure": 4, "controls": 4}},
        format="json",
    )
    assert scored.status_code == status.HTTP_200_OK, scored.data

    overridden = client.post(
        f"/api/auditable-entities/{entity.id}/override-rating/",
        {"rating": "Critical", "rationale": "Trying to overrule the engine directly."},
        format="json",
    )
    assert overridden.status_code == status.HTTP_403_FORBIDDEN


def test_cae_can_override_despite_read_only_universe_access(
    authed_client, matrix_user, entity,
):
    """The Chief audit executive holds audit_universe=READ.

    Gating the override on audit_universe edit would have locked out the one
    person whose sign-off the action exists for.
    """
    client = authed_client(matrix_user("Chief audit executive"))

    resp = client.post(
        f"/api/auditable-entities/{entity.id}/override-rating/",
        {"rating": "High", "rationale": "Carrying the prior year's committee decision forward."},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.data
    entity.refresh_from_db()
    assert entity.risk_rating == "High"


# ══════════════════════════════════════════════════════════════════════
# Factor scoring endpoint
# ══════════════════════════════════════════════════════════════════════
def test_scoring_defaults_to_the_active_model(sa_client, entity, active_model):
    resp = sa_client.put(
        f"/api/auditable-entities/{entity.id}/risk-factors/",
        {"factorValues": {"exposure": 5, "controls": 5}, "notes": "Annual refresh."},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.data
    assert resp.data["isHighRisk"] is True
    # The IIA-native 2..10 reading travels alongside the normalized composite,
    # because that is the number auditors recognise from the practice guide.
    assert resp.data["detail"]["raw_composite"] == "10.00"
    assert resp.data["entity"]["readiness"]["criteria"]


def test_scoring_without_an_active_model_says_so(sa_client, entity):
    resp = sa_client.put(
        f"/api/auditable-entities/{entity.id}/risk-factors/",
        {"factorValues": {"exposure": 3}},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "Activate one in Settings" in resp.data["detail"]


def test_scoring_rejects_an_out_of_range_rating(sa_client, entity, active_model):
    resp = sa_client.put(
        f"/api/auditable-entities/{entity.id}/risk-factors/",
        {"factorValues": {"exposure": 9, "controls": 3}},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "out of range" in resp.data["detail"]
