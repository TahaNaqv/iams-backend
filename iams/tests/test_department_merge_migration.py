"""Coverage for the Department → AuditableEntity merge.

The standalone ``Department`` model was dropped in migration 0033; departments
are now ``AuditableEntity`` rows with ``entity_type="Department"``. The
data-conversion migrations (0031 reparent + UUID-reuse, 0032 ``department_entity``
backfill) were validated end-to-end while ``Department`` still existed. They
cannot be replayed here because the test suite runs with ``--no-migrations``
(the schema is built directly from current models, which no longer contain the
``Department`` table), so this module covers the live invariant the rest of the
system now depends on: the ``get_department()`` ancestry helper that backs the
serializer's derived department.
"""
from __future__ import annotations

import pytest

from iams.models import AuditableEntity

pytestmark = pytest.mark.django_db


def test_get_department_resolves_nearest_ancestor():
    dept = AuditableEntity.objects.create(
        name="Ops", entity_type="Department", risk_rating="Medium", status="Active",
    )
    mid = AuditableEntity.objects.create(
        name="Logistics", entity_type="Function", risk_rating="Medium",
        status="Active", parent=dept,
    )
    leaf = AuditableEntity.objects.create(
        name="Inbound", entity_type="Process", risk_rating="Medium",
        status="Active", parent=mid,
    )
    assert leaf.get_department().id == dept.id
    assert mid.get_department().id == dept.id
    # A department node has no department ancestor of its own.
    assert dept.get_department() is None


def test_department_entity_link_round_trips():
    """The owning-department FK (department_entity) is the tree-native
    replacement for the dropped department_ref → Department FK."""
    dept = AuditableEntity.objects.create(
        name="Finance", entity_type="Department", risk_rating="High", status="Active",
    )
    ledger = AuditableEntity.objects.create(
        name="General Ledger", entity_type="Process", risk_rating="Medium",
        status="Active", department_entity=dept,
    )
    assert ledger.department_entity_id == dept.id
    assert dept.member_entities.filter(pk=ledger.id).exists()
