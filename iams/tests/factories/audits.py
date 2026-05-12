"""Factories for audit-domain models."""
from __future__ import annotations

from datetime import date, timedelta

import factory

from iams.models import (
    Audit,
    ChecklistItem,
    CorrectiveAction,
    Department,
    Finding,
)


class DepartmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Department
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Department {n}")
    risk_rating = "Medium"
    entity_count = 5


class AuditFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Audit

    title = factory.Sequence(lambda n: f"Audit {n}")
    department = "Finance"
    lead_auditor = "Test Lead"
    status = "Planned"
    priority = "Medium"
    risk_rating = "Medium"
    start_date = factory.LazyFunction(date.today)
    end_date = factory.LazyAttribute(lambda o: o.start_date + timedelta(days=60))
    scope = "Test scope"
    objectives = "Test objectives"
    completion_percent = 0
    findings_count = 0


class FindingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Finding

    audit = factory.SubFactory(AuditFactory)
    title = factory.Sequence(lambda n: f"Finding {n}")
    severity = "Medium"
    status = "Open"
    owner = "Test Owner"
    due_date = factory.LazyFunction(lambda: date.today() + timedelta(days=30))
    description = "Test description"
    recommendation = "Test recommendation"


class CorrectiveActionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CorrectiveAction

    finding = factory.SubFactory(FindingFactory)
    title = factory.Sequence(lambda n: f"CAP {n}")
    owner = "Test Owner"
    status = "Open"
    due_date = factory.LazyFunction(lambda: date.today() + timedelta(days=45))
    progress = 0


class CheckListItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ChecklistItem

    audit = factory.SubFactory(AuditFactory)
    title = factory.Sequence(lambda n: f"Checklist item {n}")
    status = "Pending"
    assignee = "Test"
