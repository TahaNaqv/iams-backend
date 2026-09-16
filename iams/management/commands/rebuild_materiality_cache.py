"""Rebuild AuditableEntity.materiality_cache from EntityMaterialityValue rows.

The cache is a derived mirror used for register sorting and range filters.
Run this after a bulk import, after toggling metric definitions, or any time
the cache is suspected of having drifted — it is safe to run at any time and
rewrites only the entities whose cache actually changed.
"""
from django.core.management.base import BaseCommand

from iams.materiality import rebuild_all


class Command(BaseCommand):
    help = "Rebuild the denormalised materiality sort cache for every entity."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Entities to load per batch (default: 500).",
        )

    def handle(self, *args, **options):
        changed = rebuild_all(batch_size=options["batch_size"])
        self.stdout.write(
            self.style.SUCCESS(f"Materiality cache rebuilt; {changed} entities updated.")
        )
