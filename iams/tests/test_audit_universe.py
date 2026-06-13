"""End-to-end tests for the Phase-7 audit-universe API.

Covers:

* CRUD on AuditableEntity, including legacy back-compat fields
* Soft-delete (DELETE + archive action), restore
* Choice validation on risk_rating / status / entity_type / compliance_status
* Hierarchy: parent FK, cycle prevention, tree endpoint, lineage
* Tags JSONField with multi-value filters
* Optimistic locking via the ``version`` field
* Filters & search: q, status, riskRating, businessUnit, tagsAny, mine,
  overdue, dueWithinDays, neverAudited
* Custom actions: kpis, coverage, revisions, clone, archive, restore
* RBAC: read requires view_audits; write requires create_audits /
  edit_audits; cross-role 403s
* AuditableEntityRevision append-only invariant
* New child resources: Department writable, BusinessUnit, Tag
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from rest_framework import status

from iams.models import (
    AuditableEntity,
    AuditableEntityRevision,
    BusinessUnit,
    Department,
    EntityStatusChoices,
    RiskRatingChoices,
    Tag,
)


# ══════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════
@pytest.fixture
def sa_client(super_admin, authed_client):
    return authed_client(super_admin)


@pytest.fixture
def auditor_client(auditor_user, authed_client):
    return authed_client(auditor_user)


@pytest.fixture
def manager_client(audit_manager, authed_client):
    return authed_client(audit_manager)


@pytest.fixture
def finance_dept(db) -> Department:
    return Department.objects.create(name="Finance", head="J. Doe", risk_rating="High")


@pytest.fixture
def it_dept(db) -> Department:
    return Department.objects.create(name="IT", head="K. Lin", risk_rating="Medium")


@pytest.fixture
def finance_bu(db) -> BusinessUnit:
    return BusinessUnit.objects.create(name="Finance & Treasury", code="FIN")


@pytest.fixture
def entity_ap(db, finance_dept, finance_bu) -> AuditableEntity:
    return AuditableEntity.objects.create(
        name="Accounts Payable",
        department=finance_dept.name,
        department_ref=finance_dept,
        business_unit=finance_bu,
        owner="J. Doe",
        risk_rating="High",
        inherent_likelihood=4,
        inherent_impact=5,
        tags=["sox", "critical"],
        is_mandatory_to_audit=True,
        last_audit_date=date(2025, 1, 15),
        next_audit_date=date(2026, 7, 1),
    )


# ══════════════════════════════════════════════════════════════════════
# CRUD
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_create_entity_with_full_payload(sa_client, finance_dept, finance_bu, super_admin):
    payload = {
        "name": "General Ledger Process",
        "description": "End-of-month GL close.",
        "entityType": "Process",
        "riskRating": "Medium",
        "complianceStatus": "Compliant",
        "auditFrequency": "Quarterly",
        "lastAuditRating": "Satisfactory",
        "departmentId": str(finance_dept.id),
        "businessUnitId": str(finance_bu.id),
        "primaryOwnerId": str(super_admin.id),
        "tags": ["sox", "high-volume"],
        "isMandatoryToAudit": True,
        "headcount": 8,
        "operatingBudget": "150000.50",
        "estimatedManDays": "12.50",
        "costCenterId": "FIN-1234",
        "inherentLikelihood": 3,
        "inherentImpact": 4,
        "location": "EMEA",
        "primaryLanguage": "en",
    }
    resp = sa_client.post("/api/auditable-entities/", payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED, resp.content
    body = resp.json()
    assert body["name"] == "General Ledger Process"
    assert body["riskRating"] == "Medium"
    assert body["complianceStatus"] == "Compliant"
    assert body["tags"] == ["sox", "high-volume"]
    assert body["estimatedManDays"] == "12.50"
    assert body["inherentScore"] == 12
    assert body["primaryOwner"]["id"] == str(super_admin.id)
    assert body["version"] == 1


@pytest.mark.django_db
def test_update_entity_bumps_version_and_records_revision(sa_client, entity_ap):
    resp = sa_client.patch(
        f"/api/auditable-entities/{entity_ap.id}/",
        {"riskRating": "Critical", "version": entity_ap.version},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.content
    body = resp.json()
    assert body["riskRating"] == "Critical"
    assert body["version"] == entity_ap.version + 1

    revs = AuditableEntityRevision.objects.filter(entity=entity_ap)
    assert revs.count() >= 1
    last = revs.order_by("-created_at").first()
    assert "risk_rating" in last.changes
    assert last.changes["risk_rating"]["from"] == "High"
    assert last.changes["risk_rating"]["to"] == "Critical"


@pytest.mark.django_db
def test_optimistic_lock_rejects_stale_version(sa_client, entity_ap):
    resp = sa_client.patch(
        f"/api/auditable-entities/{entity_ap.id}/",
        {"riskRating": "Critical", "version": 99},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "version" in resp.json()


# ══════════════════════════════════════════════════════════════════════
# Choice validation
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("riskRating", "Extreme"),
        ("status", "Banana"),
        ("entityType", "NotAType"),
        ("complianceStatus", "Pending"),
        ("auditFrequency", "Sometimes"),
    ],
)
def test_choice_validation_rejects_unknown_values(sa_client, finance_dept, field, bad_value):
    payload = {
        "name": f"Bad-{field}",
        "departmentId": str(finance_dept.id),
        "riskRating": "Medium",
        field: bad_value,
    }
    resp = sa_client.post("/api/auditable-entities/", payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST, resp.content
    assert field in resp.json()


@pytest.mark.django_db
@pytest.mark.parametrize("entity_type", ["Process", "Department", "Division", "Area"])
def test_entity_type_accepts_org_scopes(sa_client, finance_dept, entity_type):
    payload = {
        "name": f"Scoped-{entity_type}",
        "departmentId": str(finance_dept.id),
        "riskRating": "Medium",
        "entityType": entity_type,
    }
    resp = sa_client.post("/api/auditable-entities/", payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED, resp.content
    assert resp.json()["entityType"] == entity_type


@pytest.mark.django_db
def test_estimated_man_days_round_trips_and_records_revision(sa_client, entity_ap):
    resp = sa_client.patch(
        f"/api/auditable-entities/{entity_ap.id}/",
        {"estimatedManDays": "7.25", "version": entity_ap.version},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.content
    assert resp.json()["estimatedManDays"] == "7.25"

    last = (
        AuditableEntityRevision.objects.filter(entity=entity_ap)
        .order_by("-created_at")
        .first()
    )
    assert "estimated_man_days" in last.changes
    assert last.changes["estimated_man_days"]["to"] == "7.25"


@pytest.mark.django_db
def test_estimated_man_days_rejects_overflow(sa_client, finance_dept):
    payload = {
        "name": "Effort overflow",
        "departmentId": str(finance_dept.id),
        "riskRating": "Medium",
        "estimatedManDays": "1000000.00",  # exceeds max_digits=6
    }
    resp = sa_client.post("/api/auditable-entities/", payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "estimatedManDays" in resp.json()


@pytest.mark.django_db
def test_estimated_man_days_rejects_negative(sa_client, finance_dept):
    payload = {
        "name": "Negative effort",
        "departmentId": str(finance_dept.id),
        "riskRating": "Medium",
        "estimatedManDays": "-1.00",
    }
    resp = sa_client.post("/api/auditable-entities/", payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "estimatedManDays" in resp.json()


@pytest.mark.django_db
def test_inherent_likelihood_range_validation(sa_client, finance_dept):
    payload = {
        "name": "Out of range",
        "departmentId": str(finance_dept.id),
        "riskRating": "Medium",
        "inherentLikelihood": 9,
    }
    resp = sa_client.post("/api/auditable-entities/", payload, format="json")
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "inherentLikelihood" in resp.json()


@pytest.mark.django_db
def test_next_audit_date_must_be_after_last(sa_client, entity_ap):
    resp = sa_client.patch(
        f"/api/auditable-entities/{entity_ap.id}/",
        {
            "lastAuditDate": "2026-01-01",
            "nextAuditDate": "2025-12-01",
            "version": entity_ap.version,
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "nextAuditDate" in resp.json()


# ══════════════════════════════════════════════════════════════════════
# Hierarchy & cycle prevention
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_self_parent_rejected(sa_client, entity_ap):
    resp = sa_client.patch(
        f"/api/auditable-entities/{entity_ap.id}/",
        {"parentId": str(entity_ap.id), "version": entity_ap.version},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "parentId" in resp.json()


@pytest.mark.django_db
def test_cycle_detection_in_parent_chain(sa_client, finance_dept):
    a = AuditableEntity.objects.create(name="A", department_ref=finance_dept)
    b = AuditableEntity.objects.create(name="B", department_ref=finance_dept, parent=a)
    c = AuditableEntity.objects.create(name="C", department_ref=finance_dept, parent=b)
    # Try to make A a child of C → A->...->C->A would cycle.
    resp = sa_client.patch(
        f"/api/auditable-entities/{a.id}/",
        {"parentId": str(c.id), "version": a.version},
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_tree_endpoint_returns_nested_children(sa_client, finance_dept):
    parent = AuditableEntity.objects.create(name="Financial Operations", department_ref=finance_dept)
    AuditableEntity.objects.create(name="AP Oversight", department_ref=finance_dept, parent=parent)
    AuditableEntity.objects.create(name="Treasury Hedging", department_ref=finance_dept, parent=parent)
    resp = sa_client.get("/api/auditable-entities/tree/")
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    roots = [n for n in body if n["name"] == "Financial Operations"]
    assert roots, body
    assert len(roots[0]["children"]) == 2


@pytest.mark.django_db
def test_lineage_returns_ancestor_chain(sa_client, finance_dept):
    a = AuditableEntity.objects.create(name="A", department_ref=finance_dept)
    b = AuditableEntity.objects.create(name="B", department_ref=finance_dept, parent=a)
    c = AuditableEntity.objects.create(name="C", department_ref=finance_dept, parent=b)
    resp = sa_client.get(f"/api/auditable-entities/{c.id}/lineage/")
    assert resp.status_code == status.HTTP_200_OK
    names = [n["name"] for n in resp.json()]
    assert names == ["A", "B"]


# ══════════════════════════════════════════════════════════════════════
# Soft-delete: archive / restore / DELETE
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_archive_action_marks_status_archived(sa_client, entity_ap):
    resp = sa_client.post(f"/api/auditable-entities/{entity_ap.id}/archive/")
    assert resp.status_code == status.HTTP_200_OK
    entity_ap.refresh_from_db()
    assert entity_ap.status == "Archived"


@pytest.mark.django_db
def test_default_list_hides_archived(sa_client, entity_ap):
    entity_ap.status = "Archived"
    entity_ap.save()
    resp = sa_client.get("/api/auditable-entities/")
    ids = {r["id"] for r in resp.json()["results"]}
    assert str(entity_ap.id) not in ids


@pytest.mark.django_db
def test_include_archived_returns_archived_rows(sa_client, entity_ap):
    entity_ap.status = "Archived"
    entity_ap.save()
    resp = sa_client.get("/api/auditable-entities/?includeArchived=true")
    ids = {r["id"] for r in resp.json()["results"]}
    assert str(entity_ap.id) in ids


@pytest.mark.django_db
def test_delete_performs_soft_delete(sa_client, entity_ap):
    resp = sa_client.delete(f"/api/auditable-entities/{entity_ap.id}/")
    assert resp.status_code in (200, 204)
    entity_ap.refresh_from_db()
    assert entity_ap.status == EntityStatusChoices.ARCHIVED


@pytest.mark.django_db
def test_restore_action_reactivates(sa_client, entity_ap):
    entity_ap.status = "Archived"
    entity_ap.save()
    resp = sa_client.post(f"/api/auditable-entities/{entity_ap.id}/restore/")
    assert resp.status_code == status.HTTP_200_OK
    entity_ap.refresh_from_db()
    assert entity_ap.status == EntityStatusChoices.ACTIVE


# ══════════════════════════════════════════════════════════════════════
# Filters & search
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_filter_by_risk_rating_multi_value(sa_client, finance_dept):
    AuditableEntity.objects.create(name="Low one", department_ref=finance_dept, risk_rating="Low")
    AuditableEntity.objects.create(name="High one", department_ref=finance_dept, risk_rating="High")
    AuditableEntity.objects.create(name="Med one", department_ref=finance_dept, risk_rating="Medium")
    resp = sa_client.get("/api/auditable-entities/?riskRating=High,Low")
    names = {r["name"] for r in resp.json()["results"]}
    assert "Low one" in names and "High one" in names
    assert "Med one" not in names


@pytest.mark.django_db
def test_search_q_matches_name_or_costcenter(sa_client, finance_dept):
    AuditableEntity.objects.create(
        name="Procurement", department_ref=finance_dept, cost_center_id="PRC-9001"
    )
    resp = sa_client.get("/api/auditable-entities/?q=PRC-9001")
    assert any(r["name"] == "Procurement" for r in resp.json()["results"])


@pytest.mark.django_db
def test_tags_any_filter(sa_client, finance_dept):
    AuditableEntity.objects.create(name="A", department_ref=finance_dept, tags=["sox"])
    AuditableEntity.objects.create(name="B", department_ref=finance_dept, tags=["gdpr"])
    AuditableEntity.objects.create(name="C", department_ref=finance_dept, tags=["other"])
    resp = sa_client.get("/api/auditable-entities/?tagsAny=sox,gdpr")
    names = {r["name"] for r in resp.json()["results"]}
    assert names == {"A", "B"}


@pytest.mark.django_db
def test_mine_filter_scopes_to_request_user(sa_client, super_admin, finance_dept):
    AuditableEntity.objects.create(
        name="Mine", department_ref=finance_dept, primary_owner=super_admin
    )
    AuditableEntity.objects.create(name="Not mine", department_ref=finance_dept)
    resp = sa_client.get("/api/auditable-entities/?mine=true")
    names = {r["name"] for r in resp.json()["results"]}
    assert names == {"Mine"}


@pytest.mark.django_db
def test_overdue_and_never_audited_filters(sa_client, finance_dept):
    AuditableEntity.objects.create(
        name="Overdue", department_ref=finance_dept,
        next_audit_date=date.today() - timedelta(days=10),
    )
    AuditableEntity.objects.create(name="Never", department_ref=finance_dept)
    AuditableEntity.objects.create(
        name="Recent", department_ref=finance_dept,
        last_audit_date=date.today() - timedelta(days=30),
    )
    overdue = sa_client.get("/api/auditable-entities/?overdue=true").json()["results"]
    assert {r["name"] for r in overdue} == {"Overdue"}
    never = sa_client.get("/api/auditable-entities/?neverAudited=true").json()["results"]
    assert {"Overdue", "Never"} <= {r["name"] for r in never}


# ══════════════════════════════════════════════════════════════════════
# KPI / coverage actions
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_kpis_endpoint_returns_strip(sa_client, finance_dept):
    AuditableEntity.objects.create(name="A", department_ref=finance_dept, risk_rating="Critical")
    AuditableEntity.objects.create(name="B", department_ref=finance_dept, risk_rating="High")
    resp = sa_client.get("/api/auditable-entities/kpis/")
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert {"totalEntities", "criticalRisks", "complianceRate", "openAudits", "planProgress"} <= set(body)
    assert body["criticalRisks"] >= 1


@pytest.mark.django_db
def test_coverage_endpoint(sa_client, finance_dept):
    AuditableEntity.objects.create(name="No owner", department_ref=finance_dept)
    resp = sa_client.get("/api/auditable-entities/coverage/")
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert {"withoutOwner", "withoutNextAudit", "neverAudited", "staleOver3Years"} <= set(body)
    assert body["withoutOwner"] >= 1


@pytest.mark.django_db
def test_clone_creates_copy_with_new_name(sa_client, entity_ap):
    resp = sa_client.post(
        f"/api/auditable-entities/{entity_ap.id}/clone/",
        {"name": "AP Oversight Copy"}, format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED
    assert resp.json()["name"] == "AP Oversight Copy"
    # Source remains untouched
    entity_ap.refresh_from_db()
    assert entity_ap.name == "Accounts Payable"


# ══════════════════════════════════════════════════════════════════════
# Revisions
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_revision_appended_on_create(sa_client, finance_dept):
    resp = sa_client.post(
        "/api/auditable-entities/",
        {"name": "Test create", "departmentId": str(finance_dept.id), "riskRating": "Low"},
        format="json",
    )
    entity_id = resp.json()["id"]
    revs = AuditableEntityRevision.objects.filter(entity_id=entity_id)
    assert revs.count() == 1
    assert revs.first().comment == "Created."


@pytest.mark.django_db
def test_revisions_endpoint_lists_per_entity(sa_client, entity_ap):
    sa_client.patch(
        f"/api/auditable-entities/{entity_ap.id}/",
        {"riskRating": "Critical", "version": entity_ap.version}, format="json",
    )
    resp = sa_client.get(f"/api/auditable-entities/{entity_ap.id}/revisions/")
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    items = body.get("results", body)
    assert any("risk_rating" in (r["changes"] or {}) for r in items)


@pytest.mark.django_db
def test_revision_is_append_only(db, entity_ap):
    rev = AuditableEntityRevision.objects.create(
        entity=entity_ap, version=1, changes={"_initial": {}},
    )
    with pytest.raises(PermissionError):
        rev.comment = "Tampering"
        rev.save()
    with pytest.raises(PermissionError):
        rev.delete()


# ══════════════════════════════════════════════════════════════════════
# RBAC
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_anonymous_cannot_read_entities(api_client):
    resp = api_client.get("/api/auditable-entities/")
    assert resp.status_code in (401, 403)


@pytest.mark.django_db
def test_auditor_can_read_but_not_create(auditor_client, finance_dept):
    list_resp = auditor_client.get("/api/auditable-entities/")
    assert list_resp.status_code == status.HTTP_200_OK
    create_resp = auditor_client.post(
        "/api/auditable-entities/",
        {"name": "Forbidden", "departmentId": str(finance_dept.id), "riskRating": "Low"},
        format="json",
    )
    assert create_resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_manager_can_create_and_edit(manager_client, finance_dept):
    create_resp = manager_client.post(
        "/api/auditable-entities/",
        {"name": "Mgr-created", "departmentId": str(finance_dept.id), "riskRating": "Medium"},
        format="json",
    )
    assert create_resp.status_code == status.HTTP_201_CREATED
    eid = create_resp.json()["id"]
    upd_resp = manager_client.patch(
        f"/api/auditable-entities/{eid}/",
        {"riskRating": "High", "version": 1},
        format="json",
    )
    assert upd_resp.status_code == status.HTTP_200_OK


# ══════════════════════════════════════════════════════════════════════
# Business Units & Tags
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_business_unit_crud(sa_client, super_admin):
    resp = sa_client.post(
        "/api/business-units/",
        {"name": "Treasury", "code": "TRS", "riskAppetite": "Medium", "headId": str(super_admin.id)},
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED, resp.content
    bu_id = resp.json()["id"]
    list_resp = sa_client.get("/api/business-units/")
    assert any(b["id"] == bu_id for b in list_resp.json()["results"])


@pytest.mark.django_db
def test_business_unit_cycle_rejected(sa_client):
    a = BusinessUnit.objects.create(name="A")
    b = BusinessUnit.objects.create(name="B", parent=a)
    resp = sa_client.patch(
        f"/api/business-units/{a.id}/",
        {"parentId": str(b.id)}, format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.django_db
def test_tag_create_auto_slug(sa_client):
    resp = sa_client.post(
        "/api/tags/",
        {"name": "SOX Compliant", "category": "Compliance"},
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED
    body = resp.json()
    assert body["slug"] == "sox-compliant"


@pytest.mark.django_db
def test_department_now_writable(sa_client, finance_bu):
    resp = sa_client.post(
        "/api/departments/",
        {"name": "Logistics", "head": "M. Patel", "riskRating": "Medium",
         "businessUnitId": str(finance_bu.id)},
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED


# ══════════════════════════════════════════════════════════════════════
# Backward compatibility
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_legacy_fields_still_returned_on_list(sa_client, entity_ap):
    resp = sa_client.get("/api/auditable-entities/")
    item = resp.json()["results"][0]
    assert "department" in item  # legacy free-text
    assert "owner" in item       # legacy free-text
    assert "riskRating" in item


@pytest.mark.django_db
def test_recompute_action_with_no_active_model(sa_client):
    resp = sa_client.post("/api/auditable-entities/recompute-risk-scores/")
    # No RiskScoringModel seeded → 400 with explanatory body
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "detail" in resp.json()


# ══════════════════════════════════════════════════════════════════════
# Data-quality filters (Phase-7 Track S6 — Coverage page)
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_without_owner_filter(sa_client, super_admin, finance_dept):
    AuditableEntity.objects.create(name="No owner", department_ref=finance_dept)
    AuditableEntity.objects.create(
        name="Has owner", department_ref=finance_dept, primary_owner=super_admin,
    )
    resp = sa_client.get("/api/auditable-entities/?withoutOwner=true")
    names = {r["name"] for r in resp.json()["results"]}
    assert names == {"No owner"}


@pytest.mark.django_db
def test_without_next_audit_filter(sa_client, finance_dept):
    from datetime import date as _date
    AuditableEntity.objects.create(name="No plan", department_ref=finance_dept)
    AuditableEntity.objects.create(
        name="Planned", department_ref=finance_dept, next_audit_date=_date(2027, 1, 1),
    )
    resp = sa_client.get("/api/auditable-entities/?withoutNextAudit=true")
    names = {r["name"] for r in resp.json()["results"]}
    assert names == {"No plan"}


@pytest.mark.django_db
def test_stale_over_years_filter(sa_client, finance_dept):
    from datetime import date as _date, timedelta as _td
    AuditableEntity.objects.create(
        name="Stale", department_ref=finance_dept,
        last_audit_date=_date.today() - _td(days=365 * 4),
    )
    AuditableEntity.objects.create(
        name="Recent", department_ref=finance_dept,
        last_audit_date=_date.today() - _td(days=30),
    )
    resp = sa_client.get("/api/auditable-entities/?staleOverYears=3")
    names = {r["name"] for r in resp.json()["results"]}
    assert names == {"Stale"}


@pytest.mark.django_db
def test_mandatory_without_plan_filter(sa_client, finance_dept):
    AuditableEntity.objects.create(
        name="Compulsory orphan", department_ref=finance_dept,
        is_mandatory_to_audit=True,
    )
    AuditableEntity.objects.create(
        name="Optional", department_ref=finance_dept,
        is_mandatory_to_audit=False,
    )
    resp = sa_client.get("/api/auditable-entities/?mandatoryWithoutPlan=true")
    names = {r["name"] for r in resp.json()["results"]}
    assert names == {"Compulsory orphan"}


@pytest.mark.django_db
def test_without_risk_score_filter(sa_client, finance_dept):
    AuditableEntity.objects.create(
        name="Scored", department_ref=finance_dept,
        inherent_likelihood=3, inherent_impact=4,
    )
    AuditableEntity.objects.create(name="Unscored", department_ref=finance_dept)
    resp = sa_client.get("/api/auditable-entities/?withoutRiskScore=true")
    names = {r["name"] for r in resp.json()["results"]}
    assert names == {"Unscored"}


@pytest.mark.django_db
def test_legacy_fields_carry_deprecation_header(sa_client, entity_ap):
    """Read responses must surface the Deprecation header (RFC 8594-ish).

    The legacy ``owner`` and ``department`` CharFields are still emitted
    on the wire for backward compatibility. Operators rely on this
    header to find clients that haven't migrated to the typed FK
    fields yet — without it, the deprecation is invisible.
    """
    list_resp = sa_client.get("/api/auditable-entities/")
    assert "Deprecation" in list_resp.headers
    assert "owner" in list_resp["Deprecation"]
    assert "department" in list_resp["Deprecation"]

    detail_resp = sa_client.get(f"/api/auditable-entities/{entity_ap.id}/")
    assert "Deprecation" in detail_resp.headers


@pytest.mark.django_db
def test_create_bumps_prometheus_counter(sa_client, finance_dept):
    """Phase-7 counter increments must fire on the happy path.

    We exercise the counter via ``inc()`` and check the resulting sample
    rather than scraping ``/metrics`` — the lower-level assertion keeps
    the test independent of django-prometheus' URL wiring.
    """
    from iams import metrics as m

    before = m.audit_universe_entities_created_total._value.get()
    resp = sa_client.post(
        "/api/auditable-entities/",
        {
            "name": "Counter target",
            "departmentId": str(finance_dept.id),
            "riskRating": "Medium",
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_201_CREATED
    after = m.audit_universe_entities_created_total._value.get()
    assert after == before + 1


@pytest.mark.django_db
def test_coverage_endpoint_returns_full_breakdown(sa_client, super_admin, finance_dept):
    from datetime import date as _date, timedelta as _td
    AuditableEntity.objects.create(
        name="Good", department_ref=finance_dept,
        primary_owner=super_admin,
        last_audit_date=_date.today() - _td(days=30),
        next_audit_date=_date.today() + _td(days=180),
        inherent_likelihood=3, inherent_impact=4,
    )
    AuditableEntity.objects.create(name="No owner", department_ref=finance_dept)
    resp = sa_client.get("/api/auditable-entities/coverage/")
    assert resp.status_code == status.HTTP_200_OK
    body = resp.json()
    assert body["total"] >= 2
    assert body["withoutOwner"] >= 1
    assert "withoutRiskScore" in body


# ══════════════════════════════════════════════════════════════════════
# Entity risk roll-up (individual risks → entity likelihood/impact/rating)
# ══════════════════════════════════════════════════════════════════════
def _add_risk(client, entity_id, **over):
    payload = {
        "entityId": str(entity_id),
        "title": over.pop("title", "Risk"),
        "category": "Operational",
        "inherentLikelihood": over.pop("inherentLikelihood", 3),
        "inherentImpact": over.pop("inherentImpact", 3),
    }
    payload.update(over)
    return client.post("/api/entity-risks/", payload, format="json")


@pytest.mark.django_db
def test_adding_risk_rolls_up_to_entity(sa_client, finance_dept):
    e = AuditableEntity.objects.create(name="GL", department_ref=finance_dept)
    resp = _add_risk(sa_client, e.id, inherentLikelihood=2, inherentImpact=2)
    assert resp.status_code == status.HTTP_201_CREATED, resp.content
    e.refresh_from_db()
    assert (e.inherent_likelihood, e.inherent_impact, e.risk_rating) == (2, 2, "Low")

    # A worse risk drives the entity up to its coordinate.
    _add_risk(sa_client, e.id, inherentLikelihood=5, inherentImpact=5)
    e.refresh_from_db()
    assert (e.inherent_likelihood, e.inherent_impact, e.risk_rating) == (5, 5, "Critical")


@pytest.mark.django_db
def test_rollup_uses_residual_not_inherent(sa_client, finance_dept):
    e = AuditableEntity.objects.create(name="AR", department_ref=finance_dept)
    _add_risk(sa_client, e.id, inherentLikelihood=5, inherentImpact=5,
              residualLikelihood=2, residualImpact=2)
    e.refresh_from_db()
    assert (e.inherent_likelihood, e.inherent_impact, e.risk_rating) == (2, 2, "Low")


@pytest.mark.django_db
def test_closed_risks_excluded_from_rollup(sa_client, finance_dept):
    e = AuditableEntity.objects.create(name="Tax", department_ref=finance_dept)
    _add_risk(sa_client, e.id, inherentLikelihood=2, inherentImpact=2)
    r2 = _add_risk(sa_client, e.id, inherentLikelihood=5, inherentImpact=5).json()
    e.refresh_from_db()
    assert e.risk_rating == "Critical"
    # Close the severe risk → entity falls back to the remaining one.
    sa_client.patch(f"/api/entity-risks/{r2['id']}/", {"status": "Closed"}, format="json")
    e.refresh_from_db()
    assert (e.inherent_likelihood, e.inherent_impact, e.risk_rating) == (2, 2, "Low")


@pytest.mark.django_db
def test_manual_override_survives_rollup(sa_client, finance_dept):
    e = AuditableEntity.objects.create(name="Treasury", department_ref=finance_dept)
    # Pin the rating manually.
    resp = sa_client.patch(
        f"/api/auditable-entities/{e.id}/",
        {"riskRating": "Critical", "riskRatingIsOverridden": True, "version": e.version},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.content
    # A low risk updates L/I but must NOT change the overridden rating.
    _add_risk(sa_client, e.id, inherentLikelihood=1, inherentImpact=1)
    e.refresh_from_db()
    assert e.risk_rating == "Critical"
    assert (e.inherent_likelihood, e.inherent_impact) == (1, 1)


@pytest.mark.django_db
def test_reset_risk_overrides_recomputes(sa_client, finance_dept):
    e = AuditableEntity.objects.create(name="Payroll", department_ref=finance_dept)
    _add_risk(sa_client, e.id, inherentLikelihood=2, inherentImpact=2)
    e.refresh_from_db()
    resp = sa_client.patch(
        f"/api/auditable-entities/{e.id}/",
        {"riskRating": "Critical", "riskRatingIsOverridden": True, "version": e.version},
        format="json",
    )
    assert resp.status_code == status.HTTP_200_OK, resp.content
    e.refresh_from_db()
    assert e.risk_rating == "Critical"
    resp = sa_client.post(f"/api/auditable-entities/{e.id}/reset-risk-overrides/", {}, format="json")
    assert resp.status_code == status.HTTP_200_OK, resp.content
    e.refresh_from_db()
    assert e.risk_rating == "Low"
    assert e.risk_rating_is_overridden is False


@pytest.mark.django_db
def test_deleting_worst_risk_rerolls(sa_client, finance_dept):
    e = AuditableEntity.objects.create(name="Vendor", department_ref=finance_dept)
    _add_risk(sa_client, e.id, inherentLikelihood=2, inherentImpact=2)
    worst = _add_risk(sa_client, e.id, inherentLikelihood=4, inherentImpact=5).json()
    e.refresh_from_db()
    assert e.risk_rating == "Critical"
    sa_client.delete(f"/api/entity-risks/{worst['id']}/")
    e.refresh_from_db()
    assert (e.inherent_likelihood, e.inherent_impact, e.risk_rating) == (2, 2, "Low")


@pytest.mark.django_db
def test_entity_serializer_exposes_risk_rollup_fields(sa_client, finance_dept):
    e = AuditableEntity.objects.create(name="Investments", department_ref=finance_dept)
    _add_risk(sa_client, e.id, inherentLikelihood=4, inherentImpact=4)
    body = sa_client.get(f"/api/auditable-entities/{e.id}/?fields=full").json()
    assert body["riskCount"] == 1
    assert body["computedRating"] == "High"
    assert body["likelihoodIsOverridden"] is False
    assert len(body["risks"]) == 1


@pytest.mark.django_db
def test_auditor_cannot_add_risk(auditor_client, finance_dept):
    e = AuditableEntity.objects.create(name="ReadOnly", department_ref=finance_dept)
    resp = _add_risk(auditor_client, e.id, inherentLikelihood=3, inherentImpact=3)
    assert resp.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_clearing_override_via_entity_patch_recomputes(sa_client, finance_dept):
    e = AuditableEntity.objects.create(name="Override clear", department_ref=finance_dept)
    _add_risk(sa_client, e.id, inherentLikelihood=2, inherentImpact=2)  # auto → Low
    e.refresh_from_db()
    # Pin rating manually.
    r = sa_client.patch(
        f"/api/auditable-entities/{e.id}/",
        {"riskRating": "Critical", "riskRatingIsOverridden": True, "version": e.version},
        format="json",
    )
    assert r.status_code == status.HTTP_200_OK, r.content
    e.refresh_from_db()
    assert e.risk_rating == "Critical"
    # Flip back to Auto via the entity PATCH — must recompute, not stay stale.
    r = sa_client.patch(
        f"/api/auditable-entities/{e.id}/",
        {"riskRatingIsOverridden": False, "version": e.version},
        format="json",
    )
    assert r.status_code == status.HTTP_200_OK, r.content
    e.refresh_from_db()
    assert e.risk_rating == "Low"


@pytest.mark.django_db
def test_entity_risk_residual_requires_both_or_neither(sa_client, finance_dept):
    e = AuditableEntity.objects.create(name="Residual half", department_ref=finance_dept)
    resp = sa_client.post(
        "/api/entity-risks/",
        {
            "entityId": str(e.id),
            "title": "Half residual",
            "inherentLikelihood": 4,
            "inherentImpact": 4,
            "residualLikelihood": 2,  # impact omitted
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "residualImpact" in resp.json()


# ══════════════════════════════════════════════════════════════════════
# Custom fields (user-defined label/value pairs)
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_custom_fields_round_trip_and_clean(sa_client, finance_dept):
    payload = {
        "name": "With custom fields",
        "departmentId": str(finance_dept.id),
        "riskRating": "Medium",
        "customFields": [
            {"label": "  Regulator ", "value": " SECP "},
            {"label": "", "value": ""},  # blank row → dropped
            {"label": "Review cycle", "value": "Biannual"},
        ],
    }
    resp = sa_client.post("/api/auditable-entities/", payload, format="json")
    assert resp.status_code == status.HTTP_201_CREATED, resp.content
    cf = resp.json()["customFields"]
    assert cf == [
        {"label": "Regulator", "value": "SECP"},
        {"label": "Review cycle", "value": "Biannual"},
    ]


@pytest.mark.django_db
def test_custom_fields_reject_label_only_missing(sa_client, finance_dept):
    resp = sa_client.post(
        "/api/auditable-entities/",
        {
            "name": "Bad custom",
            "departmentId": str(finance_dept.id),
            "riskRating": "Medium",
            "customFields": [{"value": "orphan value"}],  # no label
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "customFields" in resp.json()


@pytest.mark.django_db
def test_custom_fields_reject_over_cap(sa_client, finance_dept):
    resp = sa_client.post(
        "/api/auditable-entities/",
        {
            "name": "Too many custom",
            "departmentId": str(finance_dept.id),
            "riskRating": "Medium",
            "customFields": [{"label": f"L{i}", "value": str(i)} for i in range(51)],
        },
        format="json",
    )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert "customFields" in resp.json()


# ══════════════════════════════════════════════════════════════════════
# Hierarchy tree — nesting + ordering
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_tree_nests_children_and_orders_by_name(sa_client, finance_dept):
    parent = AuditableEntity.objects.create(name="Finance", department_ref=finance_dept, entity_type="Department")
    # Children created out of alphabetical order on purpose.
    AuditableEntity.objects.create(name="Treasury", department_ref=finance_dept, parent=parent, entity_type="Division")
    AuditableEntity.objects.create(name="Accounts Payable", department_ref=finance_dept, parent=parent, entity_type="Process")

    resp = sa_client.get(f"/api/auditable-entities/tree/?root={parent.id}")
    assert resp.status_code == status.HTTP_200_OK, resp.content
    root = resp.json()[0]
    assert root["name"] == "Finance"
    child_names = [c["name"] for c in root["children"]]
    assert child_names == ["Accounts Payable", "Treasury"]  # name-ordered
