"""Performance + N+1 regressions for the audit-universe endpoints.

These tests don't make tight wall-clock assertions (CI runners vary); they
target the failure modes that *cause* slowness:

  - N+1 queries on list / tree / coverage when the page size grows
  - quadratic behaviour in the tree builder
  - missing ``select_related`` on the detail / list serializers

Wall-clock bounds are kept generous so they're not flaky on shared CI,
but the query-count assertions are tight — those are the genuine canary
for performance regressions.
"""
from __future__ import annotations

import time

import pytest
from django.test.utils import CaptureQueriesContext
from django.db import connection
from rest_framework import status

from iams.models import AuditableEntity


@pytest.fixture
def sa_client(super_admin, authed_client):
    return authed_client(super_admin)


@pytest.fixture
def universe(db, super_admin):
    """Seed a multi-department universe with hierarchical structure."""
    departments = [
        AuditableEntity.objects.create(
            name=f"Dept-{i}", entity_type="Department", status="Active"
        )
        for i in range(5)
    ]
    parents = []
    for i in range(10):
        parent = AuditableEntity.objects.create(
            name=f"P-{i}",
            department_entity=departments[i % len(departments)],
            primary_owner=super_admin,
            risk_rating="High" if i % 2 == 0 else "Medium",
            inherent_likelihood=(i % 5) + 1,
            inherent_impact=((i + 2) % 5) + 1,
        )
        parents.append(parent)
        # Each parent gets a handful of children.
        for j in range(3):
            AuditableEntity.objects.create(
                name=f"P-{i}-C-{j}",
                department_entity=departments[j % len(departments)],
                primary_owner=super_admin,
                parent=parent,
                risk_rating="Low",
            )
    return {"parents": parents, "departments": departments}


# ══════════════════════════════════════════════════════════════════════
# N+1 regressions
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_list_endpoint_is_constant_query_count(sa_client, universe):
    """List queries must stay constant regardless of page size.

    The list serializer joins ``department_ref``, ``business_unit``,
    ``primary_owner``, ``secondary_owner``, ``parent`` via
    ``select_related``. Without it, each row triggers extra SELECTs.
    We assert a small absolute ceiling — this is a tight canary against
    accidental ``foo.bar.baz`` field accesses on the list serializer.
    """
    with CaptureQueriesContext(connection) as ctx:
        resp = sa_client.get("/api/auditable-entities/?page_size=40")
        assert resp.status_code == status.HTTP_200_OK
    # 40 rows shouldn't push us above ~20 queries (count, auth/profile
    # lookups, the list itself, and a few permission checks). The
    # threshold is deliberately generous so unrelated middleware doesn't
    # flake the test, but tight enough that an N+1 (40+ extra queries)
    # would blow it.
    assert len(ctx.captured_queries) < 25, (
        f"List endpoint executed {len(ctx.captured_queries)} queries — "
        "investigate for an N+1 regression."
    )


@pytest.mark.django_db
def test_tree_endpoint_does_not_explode_with_depth(sa_client, universe):
    """The tree builder must not re-fetch each child row."""
    with CaptureQueriesContext(connection) as ctx:
        resp = sa_client.get("/api/auditable-entities/tree/?depth=5")
        assert resp.status_code == status.HTTP_200_OK
    assert len(ctx.captured_queries) < 25


@pytest.mark.django_db
def test_coverage_endpoint_uses_aggregates(sa_client, universe):
    """Coverage must answer with a small fixed set of COUNT queries."""
    with CaptureQueriesContext(connection) as ctx:
        resp = sa_client.get("/api/auditable-entities/coverage/")
        assert resp.status_code == status.HTTP_200_OK
    # 8 counters → at most ~12 queries with auth/profile setup.
    assert len(ctx.captured_queries) < 15


@pytest.mark.django_db
def test_kpis_endpoint_is_short(sa_client, universe):
    with CaptureQueriesContext(connection) as ctx:
        resp = sa_client.get("/api/auditable-entities/kpis/")
        assert resp.status_code == status.HTTP_200_OK
    assert len(ctx.captured_queries) < 15


# ══════════════════════════════════════════════════════════════════════
# Wall-clock bounds (loose; canary, not benchmark)
# ══════════════════════════════════════════════════════════════════════
@pytest.mark.django_db
def test_list_endpoint_completes_within_one_second(sa_client, super_admin):
    """List with 500 rows must respond under 1s on a typical CI runner.

    SQLite + sync test client is naturally fast for read paths, so this
    bound mainly catches accidental quadratic behaviour or sync I/O
    introduced by a regression.
    """
    dept = AuditableEntity.objects.create(
        name="Bulk", entity_type="Department", status="Active"
    )
    # 500 rows is enough to surface a real N+1 (~1k queries) but small
    # enough that seeding stays cheap.
    AuditableEntity.objects.bulk_create(
        [
            AuditableEntity(
                name=f"E-{i}",
                department_entity=dept,
                primary_owner=super_admin,
                risk_rating="Medium",
            )
            for i in range(500)
        ]
    )
    start = time.perf_counter()
    resp = sa_client.get("/api/auditable-entities/?page_size=100")
    elapsed = time.perf_counter() - start
    assert resp.status_code == status.HTTP_200_OK
    assert elapsed < 1.0, f"List took {elapsed:.2f}s — regression suspected."
