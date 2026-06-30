"""Tests for Control Self-Assessment (Phase 3 Track 3).

Coverage:
  - Questionnaire CRUD + filter by framework/status
  - Question CRUD + auto-ordering
  - Response create + answer create + submit auto-scores
  - Submit fails on draft/inactive questionnaire/empty answers
  - Weak-control dispatches notification + bumps entity risk_rating
  - Per-category scoring (design vs operating)
  - Challenge open + resolve flow + status transitions
  - Close response prevented while challenges remain open
  - Audit-log captures submit + challenge + resolve + close
  - RBAC: questionnaire writes need manage_settings; responses need authenticated
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from iams.models import (
    AuditLogEntry,
    AuditableEntity,
    CSAAnswer,
    CSAQuestion,
    CSAQuestionnaire,
    CSAResponse,
    Notification,
)
from iams.csa import (
    CSAError,
    close_response,
    compute_scores,
    open_challenge,
    resolve_challenge,
    submit_response,
)

pytestmark = pytest.mark.django_db


# ──────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────
@pytest.fixture
def questionnaire():
    q = CSAQuestionnaire.objects.create(
        title="2026 ICFR self-assessment",
        framework=CSAQuestionnaire.FRAMEWORK_COSO,
        version="1.0",
        status=CSAQuestionnaire.STATUS_ACTIVE,
        description="Annual self-assessment of financial controls",
        weak_threshold=60,
    )
    CSAQuestion.objects.create(
        questionnaire=q, control_id="COSO-CC1.1",
        text="Are SoD controls documented?",
        response_type=CSAQuestion.TYPE_YES_NO,
        category=CSAQuestion.CATEGORY_DESIGN,
        weight=2, order=1,
    )
    CSAQuestion.objects.create(
        questionnaire=q, control_id="COSO-CC2.3",
        text="Rate frequency of bank reconciliations",
        response_type=CSAQuestion.TYPE_SCALE_1_5,
        category=CSAQuestion.CATEGORY_OPERATING,
        weight=3, order=2,
    )
    CSAQuestion.objects.create(
        questionnaire=q, control_id="COSO-CC3.4",
        text="Attach evidence of last access review",
        response_type=CSAQuestion.TYPE_EVIDENCE_REQUIRED,
        category=CSAQuestion.CATEGORY_OPERATING,
        weight=2, order=3,
    )
    return q


@pytest.fixture
def entity():
    return AuditableEntity.objects.create(
        name="Finance Department", department="Finance", owner="o",
        risk_rating="Medium", status="Active",
    )


def _make_response(questionnaire, entity, responder):
    return CSAResponse.objects.create(
        questionnaire=questionnaire,
        entity=entity,
        department=entity.department,
        responder=responder,
        status=CSAResponse.STATUS_DRAFT,
    )


def _answer(response, idx: int, value: str, evidence=None):
    q = response.questionnaire.questions.order_by("order")[idx]
    return CSAAnswer.objects.create(
        response=response, question=q, value=value, evidence_file=evidence,
    )


# ══════════════════════════════════════════════════════════════════════
# Scoring math
# ══════════════════════════════════════════════════════════════════════
def test_score_all_max_returns_100(questionnaire, entity, auditor_user):
    resp = _make_response(questionnaire, entity, auditor_user)
    _answer(resp, 0, "yes")           # yes_no, weight 2 → 2/2
    _answer(resp, 1, "5")             # scale_1_5, weight 3 → 3/3
    # Q3 needs evidence — use a stub-evidence file via plain Evidence row
    from django.core.files.uploadedfile import SimpleUploadedFile
    from iams.models import Audit, EvidenceFile
    audit = Audit.objects.create(
        title="A", department="F", lead_auditor="L", status="In Progress",
        priority="Medium", risk_rating="Medium",
        start_date="2026-01-01", end_date="2026-02-01",
        scope="s", objectives="o", completion_percent=0, findings_count=0,
    )
    from django.utils import timezone as dj_timezone
    ev = EvidenceFile.objects.create(
        audit=audit, name="proof.pdf", type="pdf",
        file=SimpleUploadedFile("p.pdf", b"x", content_type="application/pdf"),
        size_kb=1, uploaded_at=dj_timezone.now(),
    )
    _answer(resp, 2, "see attached", evidence=ev)
    scores = compute_scores(resp)
    assert scores["overall"] == Decimal("100.00")


def test_score_no_answers_returns_zero(questionnaire, entity, auditor_user):
    resp = _make_response(questionnaire, entity, auditor_user)
    scores = compute_scores(resp)
    assert scores["overall"] == Decimal("0.00")


def test_score_per_category(questionnaire, entity, auditor_user):
    resp = _make_response(questionnaire, entity, auditor_user)
    _answer(resp, 0, "yes")  # design, weight 2 → full
    _answer(resp, 1, "3")    # operating, weight 3 → 50%
    scores = compute_scores(resp)
    assert scores["design"] == Decimal("100.00")
    # operating: q2 earns 0.5 * 3 = 1.5; q3 earns 0; total = 1.5/5 = 30%
    assert scores["operating"] == Decimal("30.00")


def test_score_scale_1_5_linear_mapping(questionnaire, entity, auditor_user):
    resp = _make_response(questionnaire, entity, auditor_user)
    # only the scale_1_5 question is answered with "1" (→ 0% credit)
    _answer(resp, 1, "1")
    scores = compute_scores(resp)
    # Total weight = 2 + 3 + 2 = 7, earned = 0 → 0.00
    assert scores["overall"] == Decimal("0.00")


def test_score_evidence_required_needs_file(questionnaire, entity, auditor_user):
    resp = _make_response(questionnaire, entity, auditor_user)
    _answer(resp, 2, "Filled but no file")  # no evidence → 0
    scores = compute_scores(resp)
    assert scores["overall"] == Decimal("0.00")


# ══════════════════════════════════════════════════════════════════════
# Submit
# ══════════════════════════════════════════════════════════════════════
def test_submit_locks_response_and_computes_scores(
    questionnaire, entity, auditor_user, audit_manager
):
    resp = _make_response(questionnaire, entity, auditor_user)
    _answer(resp, 0, "yes")
    _answer(resp, 1, "5")
    submit_response(resp, by_user=auditor_user)
    resp.refresh_from_db()
    assert resp.status == CSAResponse.STATUS_SUBMITTED
    assert resp.submitted_at is not None
    assert resp.score_overall > 0


def test_submit_fails_on_already_submitted(questionnaire, entity, auditor_user):
    resp = _make_response(questionnaire, entity, auditor_user)
    _answer(resp, 0, "yes")
    submit_response(resp, by_user=auditor_user)
    with pytest.raises(CSAError, match="expected 'draft'"):
        submit_response(resp, by_user=auditor_user)


def test_submit_fails_on_inactive_questionnaire(questionnaire, entity, auditor_user):
    questionnaire.status = CSAQuestionnaire.STATUS_DRAFT
    questionnaire.save(update_fields=["status"])
    resp = _make_response(questionnaire, entity, auditor_user)
    _answer(resp, 0, "yes")
    with pytest.raises(CSAError, match="against a 'draft'"):
        submit_response(resp, by_user=auditor_user)


def test_submit_fails_on_empty_response(questionnaire, entity, auditor_user):
    resp = _make_response(questionnaire, entity, auditor_user)
    with pytest.raises(CSAError, match="empty response"):
        submit_response(resp, by_user=auditor_user)


# ══════════════════════════════════════════════════════════════════════
# Weak-control side effects
# ══════════════════════════════════════════════════════════════════════
def test_weak_control_dispatches_notification_to_audit_managers(
    questionnaire, entity, auditor_user, audit_manager
):
    Notification.objects.all().delete()
    resp = _make_response(questionnaire, entity, auditor_user)
    # All zeros → score 0 → is_weak
    _answer(resp, 0, "no")
    _answer(resp, 1, "1")
    _answer(resp, 2, "")
    submit_response(resp, by_user=auditor_user)
    resp.refresh_from_db()
    assert resp.is_weak is True
    # Audit Manager received a CSA notification
    assert Notification.objects.filter(
        recipient=audit_manager, module="CSA",
    ).exists()


def test_weak_control_bumps_entity_risk_rating_to_high(
    questionnaire, entity, auditor_user, audit_manager
):
    assert entity.risk_rating == "Medium"
    resp = _make_response(questionnaire, entity, auditor_user)
    _answer(resp, 0, "no")
    _answer(resp, 1, "1")
    submit_response(resp, by_user=auditor_user)
    entity.refresh_from_db()
    assert entity.risk_rating == "High"


def test_weak_control_does_not_demote_critical(
    questionnaire, auditor_user, audit_manager
):
    entity = AuditableEntity.objects.create(
        name="High-risk dept", department="X", owner="o",
        risk_rating="Critical", status="Active",
    )
    resp = _make_response(questionnaire, entity, auditor_user)
    _answer(resp, 0, "no")
    submit_response(resp, by_user=auditor_user)
    entity.refresh_from_db()
    # Critical must NOT be demoted to High
    assert entity.risk_rating == "Critical"


# ══════════════════════════════════════════════════════════════════════
# Challenge workflow
# ══════════════════════════════════════════════════════════════════════
def test_open_challenge_moves_response_to_under_review(
    questionnaire, entity, auditor_user, audit_manager
):
    resp = _make_response(questionnaire, entity, auditor_user)
    _answer(resp, 0, "yes")
    submit_response(resp, by_user=auditor_user)
    answer = resp.answers.first()
    open_challenge(answer, by_user=audit_manager, note="Please attach SoD matrix")
    resp.refresh_from_db()
    answer.refresh_from_db()
    assert resp.status == CSAResponse.STATUS_UNDER_REVIEW
    assert answer.challenge_status == CSAAnswer.CHALLENGE_OPEN
    assert answer.challenged_by == audit_manager


def test_cannot_challenge_draft_response(
    questionnaire, entity, auditor_user, audit_manager
):
    resp = _make_response(questionnaire, entity, auditor_user)
    answer = _answer(resp, 0, "yes")
    with pytest.raises(CSAError, match="draft"):
        open_challenge(answer, by_user=audit_manager, note="x")


def test_challenge_requires_note(questionnaire, entity, auditor_user, audit_manager):
    resp = _make_response(questionnaire, entity, auditor_user)
    _answer(resp, 0, "yes")
    submit_response(resp, by_user=auditor_user)
    answer = resp.answers.first()
    with pytest.raises(CSAError, match="note is required"):
        open_challenge(answer, by_user=audit_manager, note="")


def test_resolve_challenge_clears_under_review_when_last(
    questionnaire, entity, auditor_user, audit_manager
):
    resp = _make_response(questionnaire, entity, auditor_user)
    _answer(resp, 0, "yes")
    _answer(resp, 1, "5")
    submit_response(resp, by_user=auditor_user)
    a1, a2 = list(resp.answers.order_by("question__order"))
    open_challenge(a1, by_user=audit_manager, note="?")
    open_challenge(a2, by_user=audit_manager, note="?")
    resolve_challenge(a1, by_user=auditor_user, note="addressed")
    resp.refresh_from_db()
    assert resp.status == CSAResponse.STATUS_UNDER_REVIEW  # one still open
    resolve_challenge(a2, by_user=auditor_user, note="addressed")
    resp.refresh_from_db()
    assert resp.status == CSAResponse.STATUS_SUBMITTED  # back to submitted


def test_close_response_blocked_while_challenges_open(
    questionnaire, entity, auditor_user, audit_manager
):
    resp = _make_response(questionnaire, entity, auditor_user)
    _answer(resp, 0, "yes")
    submit_response(resp, by_user=auditor_user)
    answer = resp.answers.first()
    open_challenge(answer, by_user=audit_manager, note="?")
    with pytest.raises(CSAError, match="challenges remain open"):
        close_response(resp, by_user=audit_manager)


def test_close_response_after_resolution(
    questionnaire, entity, auditor_user, audit_manager
):
    resp = _make_response(questionnaire, entity, auditor_user)
    _answer(resp, 0, "yes")
    submit_response(resp, by_user=auditor_user)
    answer = resp.answers.first()
    open_challenge(answer, by_user=audit_manager, note="?")
    resolve_challenge(answer, by_user=auditor_user, note="ok")
    close_response(resp, by_user=audit_manager)
    resp.refresh_from_db()
    assert resp.status == CSAResponse.STATUS_CLOSED
    assert resp.closed_at is not None


# ══════════════════════════════════════════════════════════════════════
# API: submit + challenge + audit log
# ══════════════════════════════════════════════════════════════════════
def test_api_submit_endpoint_records_audit_log(
    authed_client, super_admin, questionnaire, entity
):
    resp = _make_response(questionnaire, entity, super_admin)
    _answer(resp, 0, "yes")
    AuditLogEntry.objects.filter(action="other").delete()

    res = authed_client(super_admin).post(f"/api/csa/responses/{resp.id}/submit/")
    assert res.status_code == 200, res.content
    body = res.json()
    assert body["status"] == "submitted"
    assert AuditLogEntry.objects.filter(
        details__event="csa_response_submitted",
    ).exists()


def test_api_challenge_then_resolve(
    authed_client, super_admin, audit_manager, questionnaire, entity
):
    resp = _make_response(questionnaire, entity, super_admin)
    _answer(resp, 0, "yes")
    submit_response(resp, by_user=super_admin)
    answer = resp.answers.first()

    mgr = authed_client(audit_manager)
    res1 = mgr.post(
        f"/api/csa/answers/{answer.id}/challenge/",
        {"note": "Need backing documentation"}, format="json",
    )
    assert res1.status_code == 200, res1.content
    assert res1.json()["challengeStatus"] == "open"

    res2 = authed_client(super_admin).post(
        f"/api/csa/answers/{answer.id}/resolve/",
        {"note": "Attached link in description"}, format="json",
    )
    assert res2.status_code == 200, res2.content
    assert res2.json()["challengeStatus"] == "resolved"


def test_api_submit_rejected_when_not_owner_user_unauthenticated(
    api_client, questionnaire, entity, auditor_user
):
    resp = _make_response(questionnaire, entity, auditor_user)
    res = api_client.post(f"/api/csa/responses/{resp.id}/submit/")
    assert res.status_code == 401


def test_api_questionnaire_write_requires_engagements_edit(
    authed_client, auditor_user, audit_manager, super_admin
):
    """Phase 8: CSA questionnaires are gated to the engagements module.

    A read-only engagements role (Auditor) is denied write; an editor
    (Audit manager) and super_admin are allowed.
    """
    def payload(version):
        return {"title": "Q1", "framework": "COSO", "version": version, "status": "draft", "weakThreshold": 60}

    # Auditor has engagements=read only → 403.
    res = authed_client(auditor_user).post(
        "/api/csa/questionnaires/", payload("1.0"), format="json"
    )
    assert res.status_code == 403
    # Audit manager has engagements=edit → 201.
    res2 = authed_client(audit_manager).post(
        "/api/csa/questionnaires/", payload("1.1"), format="json"
    )
    assert res2.status_code == 201
    # super_admin can.
    res3 = authed_client(super_admin).post(
        "/api/csa/questionnaires/", payload("1.2"), format="json"
    )
    assert res3.status_code == 201


def test_api_filter_responses_weak_only(
    authed_client, super_admin, questionnaire, entity, auditor_user
):
    weak = _make_response(questionnaire, entity, auditor_user)
    _answer(weak, 0, "no")
    submit_response(weak, by_user=auditor_user)
    # entity is now risk=High; need a separate entity for the strong response
    other_entity = AuditableEntity.objects.create(
        name="Treasury", department="Finance", owner="o",
        risk_rating="Medium", status="Active",
    )
    strong = _make_response(questionnaire, other_entity, auditor_user)
    _answer(strong, 0, "yes")
    _answer(strong, 1, "5")
    _answer(strong, 2, "")
    submit_response(strong, by_user=auditor_user)
    body = authed_client(super_admin).get("/api/csa/responses/?weak=true").json()
    rows = body["results"] if isinstance(body, dict) else body
    assert all(r["isWeak"] is True for r in rows)
    assert any(r["id"] == str(weak.id) for r in rows)
    assert not any(r["id"] == str(strong.id) for r in rows)
