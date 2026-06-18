"""django-filter FilterSets for the audit-universe API.

These classes back the typed query-string filters exposed by the
``AuditableEntity`` and ``Department`` viewsets. Behaviour decisions:

* Multi-value filters (``status``, ``riskRating``, ``entityType``, etc.)
  use ``__in`` lookups so the FE can pass ``?riskRating=High,Critical``.
* ``q`` is a convenience param that ORs over name / description /
  cost_center_id / department name / business-unit name — used by the
  global "Search universe..." input in the page header.
* ``mine`` resolves to "primary or secondary owner = request.user"
  via a custom method. Without a request in scope it returns an
  unmodified queryset.
* ``dueWithinDays`` filters entities whose ``next_audit_date`` is
  within N days from today (inclusive).
"""

from __future__ import annotations

from datetime import date, timedelta

import django_filters
from django.db import connection
from django.db.models import Q

from iams.models import AuditableEntity, BusinessUnit, Tag


def _tag_match_q(tag: str) -> Q:
    """Vendor-aware predicate to match an entity whose ``tags`` JSON array
    contains ``tag``.

    * Postgres / MySQL / Oracle: ``tags__contains=[tag]`` (native JSON op).
    * SQLite (tests / dev): fall back to a string substring search of the
      JSON representation, which is correct for the well-formed lists we
      always produce.
    """
    if connection.vendor == "sqlite":
        return Q(tags__icontains=f'"{tag}"')
    return Q(tags__contains=[tag])


class CSVCharFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    """Accepts a comma-separated list of values, matched via ``__in``."""


class CSVUUIDFilter(django_filters.BaseInFilter, django_filters.UUIDFilter):
    """Same as ``CSVCharFilter`` but coerces to UUID."""


class AuditableEntityFilter(django_filters.FilterSet):
    status = CSVCharFilter(field_name="status", lookup_expr="in")
    riskRating = CSVCharFilter(field_name="risk_rating", lookup_expr="in")
    complianceStatus = CSVCharFilter(field_name="compliance_status", lookup_expr="in")
    entityType = CSVCharFilter(field_name="entity_type", lookup_expr="in")
    auditFrequency = CSVCharFilter(field_name="audit_frequency", lookup_expr="in")

    businessUnit = CSVUUIDFilter(field_name="business_unit_id", lookup_expr="in")
    department = CSVUUIDFilter(field_name="department_entity_id", lookup_expr="in")
    parent = django_filters.UUIDFilter(field_name="parent_id")
    primaryOwner = django_filters.UUIDFilter(field_name="primary_owner_id")
    secondaryOwner = django_filters.UUIDFilter(field_name="secondary_owner_id")

    isMandatoryToAudit = django_filters.BooleanFilter(field_name="is_mandatory_to_audit")
    costCenterId = django_filters.CharFilter(field_name="cost_center_id", lookup_expr="iexact")

    lastAuditDateFrom = django_filters.DateFilter(field_name="last_audit_date", lookup_expr="gte")
    lastAuditDateTo = django_filters.DateFilter(field_name="last_audit_date", lookup_expr="lte")
    nextAuditDateFrom = django_filters.DateFilter(field_name="next_audit_date", lookup_expr="gte")
    nextAuditDateTo = django_filters.DateFilter(field_name="next_audit_date", lookup_expr="lte")

    tag = django_filters.CharFilter(method="filter_tag")
    tagsAny = django_filters.CharFilter(method="filter_tags_any")
    tagsAll = django_filters.CharFilter(method="filter_tags_all")

    mine = django_filters.BooleanFilter(method="filter_mine")
    dueWithinDays = django_filters.NumberFilter(method="filter_due_within")
    overdue = django_filters.BooleanFilter(method="filter_overdue")
    neverAudited = django_filters.BooleanFilter(method="filter_never_audited")

    # ── Data-quality predicates ───────────────────────────────────────
    # These back the Coverage page's drill-downs: each tile links to the
    # entity list with one of these query params, so users can act on
    # the specific rows that fail a quality rule rather than wading
    # through the whole universe.
    withoutOwner = django_filters.BooleanFilter(method="filter_without_owner")
    withoutDepartment = django_filters.BooleanFilter(method="filter_without_department")
    withoutNextAudit = django_filters.BooleanFilter(method="filter_without_next_audit")
    staleOverYears = django_filters.NumberFilter(method="filter_stale_over_years")
    mandatoryWithoutPlan = django_filters.BooleanFilter(method="filter_mandatory_without_plan")
    withoutRiskScore = django_filters.BooleanFilter(method="filter_without_risk_score")

    q = django_filters.CharFilter(method="filter_q")

    class Meta:
        model = AuditableEntity
        fields: list[str] = []

    # ── Custom filter methods ─────────────────────────────────────────
    def filter_tag(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(_tag_match_q(value))

    def filter_tags_any(self, queryset, name, value):
        tokens = [t.strip() for t in value.split(",") if t.strip()]
        if not tokens:
            return queryset
        q = Q()
        for t in tokens:
            q |= _tag_match_q(t)
        return queryset.filter(q)

    def filter_tags_all(self, queryset, name, value):
        tokens = [t.strip() for t in value.split(",") if t.strip()]
        for t in tokens:
            queryset = queryset.filter(_tag_match_q(t))
        return queryset

    def filter_mine(self, queryset, name, value):
        request = getattr(self, "request", None)
        if not value or request is None or not request.user.is_authenticated:
            return queryset
        return queryset.filter(
            Q(primary_owner=request.user) | Q(secondary_owner=request.user)
        )

    def filter_due_within(self, queryset, name, value):
        try:
            days = int(value)
        except (TypeError, ValueError):
            return queryset
        cutoff = date.today() + timedelta(days=days)
        return queryset.filter(next_audit_date__lte=cutoff, next_audit_date__gte=date.today())

    def filter_overdue(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(next_audit_date__lt=date.today())

    def filter_never_audited(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(last_audit_date__isnull=True)

    def filter_without_owner(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(primary_owner__isnull=True)

    def filter_without_department(self, queryset, name, value):
        if not value:
            return queryset
        # An entity is "without a department" when it has neither an explicit
        # owning department entity nor a Department-type ancestor. The latter
        # is approximated by the denormalized link; entities re-parented under
        # a department node carry ``department_entity`` after migration 0032.
        return queryset.filter(department_entity__isnull=True).exclude(
            entity_type="Department"
        )

    def filter_without_next_audit(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(next_audit_date__isnull=True)

    def filter_stale_over_years(self, queryset, name, value):
        try:
            years = int(value)
        except (TypeError, ValueError):
            return queryset
        cutoff = date.today() - timedelta(days=365 * max(years, 0))
        return queryset.filter(last_audit_date__lt=cutoff)

    def filter_mandatory_without_plan(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            is_mandatory_to_audit=True, next_audit_date__isnull=True
        )

    def filter_without_risk_score(self, queryset, name, value):
        if not value:
            return queryset
        # An entity has a "risk score" when both inherent axes are set;
        # the risk-engine snapshot is opt-in and not required for this
        # data-quality definition.
        return queryset.filter(
            Q(inherent_likelihood__isnull=True) | Q(inherent_impact__isnull=True)
        )

    def filter_q(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(
            Q(name__icontains=value)
            | Q(description__icontains=value)
            | Q(cost_center_id__icontains=value)
            | Q(department__icontains=value)
            | Q(department_entity__name__icontains=value)
            | Q(business_unit__name__icontains=value)
        ).distinct()


class BusinessUnitFilter(django_filters.FilterSet):
    parent = django_filters.UUIDFilter(field_name="parent_id")
    head = django_filters.UUIDFilter(field_name="head_id")
    riskAppetite = CSVCharFilter(field_name="risk_appetite", lookup_expr="in")
    q = django_filters.CharFilter(method="filter_q")

    class Meta:
        model = BusinessUnit
        fields: list[str] = []

    def filter_q(self, queryset, name, value):
        if not value:
            return queryset
        return queryset.filter(Q(name__icontains=value) | Q(code__icontains=value))


class TagFilter(django_filters.FilterSet):
    category = CSVCharFilter(field_name="category", lookup_expr="in")
    q = django_filters.CharFilter(field_name="name", lookup_expr="icontains")

    class Meta:
        model = Tag
        fields: list[str] = []
