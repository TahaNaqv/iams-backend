"""Seed Business Units, Departments, Tags, and a handful of sample
auditable entities so the Audit Universe page is usable out of the box.

Idempotent: every row goes through ``get_or_create`` so re-running the
command is safe. Use ``--clear`` to wipe the universe and reseed.

Typical invocation:

    python manage.py seed_audit_universe
    python manage.py seed_audit_universe --clear
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from iams.models import (
    AuditableEntity,
    BusinessUnit,
    Department,
    Tag,
)


BUSINESS_UNITS = [
    {"name": "Finance & Treasury", "code": "FIN", "risk_appetite": "Medium"},
    {"name": "Technology", "code": "TECH", "risk_appetite": "Medium"},
    {"name": "Operations", "code": "OPS", "risk_appetite": "Medium"},
    {"name": "Human Capital", "code": "HC", "risk_appetite": "Low"},
    {"name": "Compliance & Legal", "code": "LEG", "risk_appetite": "Low"},
]

DEPARTMENTS = [
    ("Finance", "FIN"),
    ("Treasury", "FIN"),
    ("Information Technology", "TECH"),
    ("Cybersecurity", "TECH"),
    ("Procurement", "OPS"),
    ("Supply Chain", "OPS"),
    ("Human Resources", "HC"),
    ("Legal", "LEG"),
    ("Internal Audit", "LEG"),
]

TAGS = [
    {"name": "SOX", "slug": "sox", "category": "Compliance", "color": "#1e40af"},
    {"name": "GDPR", "slug": "gdpr", "category": "Regulatory", "color": "#7c3aed"},
    {"name": "PCI-DSS", "slug": "pci-dss", "category": "Regulatory", "color": "#0891b2"},
    {"name": "Critical", "slug": "critical", "category": "Risk", "color": "#dc2626"},
    {"name": "High-volume", "slug": "high-volume", "category": "Functional", "color": "#059669"},
]

ENTITIES = [
    # (name, department, entity_type, risk_rating, mandatory)
    ("Accounts Payable", "Finance", "Process", "High", True),
    ("Accounts Receivable", "Finance", "Process", "Medium", False),
    ("General Ledger", "Finance", "Process", "High", True),
    ("Cash Management", "Treasury", "Function", "Critical", True),
    ("Network Infrastructure", "Information Technology", "System", "High", True),
    ("Cloud Operations", "Information Technology", "System", "Medium", False),
    ("Identity & Access Management", "Cybersecurity", "Process", "Critical", True),
    ("Vendor Management", "Procurement", "Process", "Medium", False),
    ("Inventory Control", "Supply Chain", "Process", "Medium", False),
    ("Payroll", "Human Resources", "Process", "High", True),
    ("Contract Management", "Legal", "Function", "Medium", False),
]


class Command(BaseCommand):
    help = (
        "Seed the Audit Universe with sample Business Units, Departments, "
        "Tags, and Auditable Entities."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Delete existing Audit-Universe rows before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["clear"]:
            self.stdout.write("Clearing existing universe rows...")
            AuditableEntity.all_objects.all().delete()
            Tag.objects.all().delete()
            Department.objects.all().delete()
            BusinessUnit.objects.all().delete()

        # ── Business Units ──
        bu_by_code: dict[str, BusinessUnit] = {}
        for bu in BUSINESS_UNITS:
            obj, _ = BusinessUnit.objects.get_or_create(
                name=bu["name"],
                defaults={"code": bu["code"], "risk_appetite": bu["risk_appetite"]},
            )
            bu_by_code[bu["code"]] = obj
        self.stdout.write(f"  Business units: {len(bu_by_code)}")

        # ── Departments (Department-type entities, linked to BU) ──
        # Departments are auditable entities now — top-level nodes of the
        # universe tree with ``entity_type="Department"``.
        dept_by_name: dict[str, AuditableEntity] = {}
        for name, bu_code in DEPARTMENTS:
            obj, _ = AuditableEntity.all_objects.get_or_create(
                name=name,
                entity_type="Department",
                defaults={
                    "risk_rating": "Medium",
                    "status": "Active",
                    "business_unit": bu_by_code.get(bu_code),
                },
            )
            if obj.business_unit_id is None and bu_code in bu_by_code:
                obj.business_unit = bu_by_code[bu_code]
                obj.save(update_fields=["business_unit", "updated_at"])
            dept_by_name[name] = obj
        self.stdout.write(f"  Departments:    {len(dept_by_name)}")

        # ── Tags ──
        for tag in TAGS:
            Tag.objects.get_or_create(
                name=tag["name"],
                defaults={
                    "slug": tag["slug"],
                    "category": tag["category"],
                    "color": tag["color"],
                },
            )
        self.stdout.write(f"  Tags:           {len(TAGS)}")

        # ── Sample entities ──
        created = 0
        for name, dept_name, entity_type, risk, mandatory in ENTITIES:
            dept = dept_by_name.get(dept_name)
            obj, was_created = AuditableEntity.all_objects.get_or_create(
                name=name,
                defaults={
                    "department": dept_name,
                    "department_entity": dept,
                    "parent": dept,
                    "business_unit": dept.business_unit if dept else None,
                    "entity_type": entity_type,
                    "risk_rating": risk,
                    "is_mandatory_to_audit": mandatory,
                    "audit_frequency": "Annual",
                    "compliance_status": "NotAssessed",
                    "inherent_likelihood": 3,
                    "inherent_impact": 4,
                },
            )
            if was_created:
                created += 1
        self.stdout.write(f"  Entities:       {created} created, {len(ENTITIES) - created} existed")

        self.stdout.write(self.style.SUCCESS("Audit Universe seed complete."))
