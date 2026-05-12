"""Seed default approval chain templates.

Run on first deploy (or when adopting Phase 2) to populate the active
chain template per request type. Idempotent: skips rows that already
exist by name and only touches the ``is_active`` flag when explicitly
told to via ``--activate``.

    python manage.py seed_approval_chains              # create-if-missing
    python manage.py seed_approval_chains --activate   # also force-activate
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from iams.models import ApprovalChainTemplate


DEFAULT_CHAINS: list[dict] = [
    {
        "name": "Annual Audit Plan — default",
        "request_type": "Audit Plan",
        "description": "FR-PLAN-06: Auditor → Manager → CAE → Board. SLA in days.",
        "chain": [
            {"role": "Audit Manager", "sla_days": 3},
            {"role": "CAE", "sla_days": 5},
            {"role": "Board", "sla_days": 14},
        ],
    },
    {
        "name": "CAP Closure — default",
        "request_type": "CAP Closure",
        "description": "FR-CAP-06: Lead Auditor validates → Audit Manager signs off.",
        "chain": [
            {"role": "Lead Auditor", "sla_days": 3},
            {"role": "Audit Manager", "sla_days": 5},
        ],
    },
    {
        "name": "Finding — default",
        "request_type": "Finding",
        "description": "Lead Auditor → Audit Manager sign-off for high-severity findings.",
        "chain": [
            {"role": "Lead Auditor", "sla_days": 2},
            {"role": "Audit Manager", "sla_days": 5},
        ],
    },
    {
        "name": "Audit Report — default",
        "request_type": "Report",
        "description": "FR-ENG-06: multi-level review before final publication.",
        "chain": [
            {"role": "Lead Auditor", "sla_days": 3},
            {"role": "Audit Manager", "sla_days": 5},
            {"role": "CAE", "sla_days": 7},
        ],
    },
    {
        "name": "Risk Assessment — default",
        "request_type": "Risk Assessment",
        "description": "Manager-only approval for annual risk-register updates.",
        "chain": [
            {"role": "Audit Manager", "sla_days": 7},
        ],
    },
]


class Command(BaseCommand):
    help = "Seed default approval chain templates (one per request type)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--activate",
            action="store_true",
            help="Force-activate the seeded templates (deactivates any other "
            "active template for the same request_type).",
        )

    @transaction.atomic
    def handle(self, *args, activate: bool = False, **opts):  # type: ignore[override]
        created = 0
        skipped = 0
        activated = 0

        for entry in DEFAULT_CHAINS:
            template, was_created = ApprovalChainTemplate.objects.get_or_create(
                name=entry["name"],
                defaults={
                    "request_type": entry["request_type"],
                    "description": entry["description"],
                    "chain": entry["chain"],
                    "is_active": activate,  # only flip active on first create if user opts in
                },
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"  + {template.name}"))
            else:
                skipped += 1

            if activate and not template.is_active:
                # Deactivate any other active template for this request_type
                # (the unique-active constraint enforces this anyway, but
                # making it explicit improves the error message).
                ApprovalChainTemplate.objects.filter(
                    request_type=entry["request_type"], is_active=True,
                ).exclude(pk=template.pk).update(is_active=False)
                template.is_active = True
                template.save(update_fields=["is_active"])
                activated += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done. {created} created, {skipped} skipped"
            + (f", {activated} (re)activated" if activate else "")
        ))
