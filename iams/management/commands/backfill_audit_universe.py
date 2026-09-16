"""Run the Audit Universe v2 data backfills against the live models.

Migrations 0050-0053 perform the same work, but a large universe is better
done deliberately: run this in a maintenance window with ``--dry-run`` first,
read the report, then run it for real. The migrations afterwards find nothing
left to do and complete in milliseconds.

    manage.py backfill_audit_universe --dry-run
    manage.py backfill_audit_universe --only links --dry-run
    manage.py backfill_audit_universe

Every step is idempotent, so running this more than once is safe, and running
it before *and* after the deploy is safe.

``--only links --dry-run`` is worth running on its own before the deploy: it
reports entities whose stored business unit or owning department disagrees
with their parent chain. The backfill never overwrites those — it only fills
blanks — so each disagreement is a question for the audit team.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from iams.backfills import (
    backfill_entity_codes,
    derive_structural_links,
    migrate_inherent_risk_to_register,
    migrate_materiality_values,
)
from iams.materiality import rebuild_all

STEPS = ("codes", "links", "materiality", "risks")


class Command(BaseCommand):
    help = "Run the Audit Universe v2 backfills (codes, links, materiality, risks)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            choices=STEPS,
            action="append",
            dest="only",
            help="Run just this step; repeatable. Default: every step, in order.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Rows per bulk write (default: 500).",
        )

    def handle(self, *args, **options):
        from iams.models import (
            AuditableEntity,
            EntityMaterialityValue,
            EntityRisk,
            MaterialityMetricDefinition,
        )

        steps = options["only"] or list(STEPS)
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        if batch_size < 1:
            raise CommandError("--batch-size must be at least 1.")

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — nothing will be written.\n"))

        # One transaction so a failure part-way leaves no half-applied state.
        # A dry run still opens it and rolls back, which also exercises the
        # same code path the real run will take.
        with transaction.atomic():
            if "codes" in steps:
                report = backfill_entity_codes(
                    AuditableEntity, dry_run=dry_run, batch_size=batch_size,
                )
                self._section("Entity codes")
                self._line("without a code", report["scanned"])
                self._line("assigned", report["assigned"])
                for prefix, count in sorted(report["by_prefix"].items()):
                    self._line(f"  {prefix}-*", count)

            if "links" in steps:
                report = derive_structural_links(
                    AuditableEntity, dry_run=dry_run, batch_size=batch_size,
                )
                self._section("Structural links")
                self._line("entities scanned", report["scanned"])
                self._line("department filled", report["department_filled"])
                self._line("business unit filled", report["business_unit_filled"])
                self._mismatches(
                    "department", report["department_mismatches"],
                )
                self._mismatches(
                    "business unit", report["business_unit_mismatches"],
                )

            if "materiality" in steps:
                report = migrate_materiality_values(
                    AuditableEntity,
                    MaterialityMetricDefinition,
                    EntityMaterialityValue,
                    dry_run=dry_run,
                )
                self._section("Materiality values")
                self._line("values created", report["created"])
                self._line("already present", report["skipped_existing"])
                if report["missing_definitions"]:
                    self.stdout.write(self.style.ERROR(
                        "  metric definitions missing, step incomplete: "
                        + ", ".join(report["missing_definitions"])
                        + "\n  Re-seed them before relying on the register."
                    ))
                if report["created"] and not dry_run:
                    changed = rebuild_all(batch_size=batch_size)
                    self._line("sort caches rebuilt", changed)

            if "risks" in steps:
                report = migrate_inherent_risk_to_register(
                    AuditableEntity, EntityRisk, dry_run=dry_run,
                )
                self._section("Inherent assessments moved to the register")
                self._line("entities with an inherent pair", report["scanned"])
                self._line("risk rows created", report["created"])
                self._line("skipped, already have risks", report["skipped_has_risks"])

            if dry_run:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(
            "Dry run complete — no changes written."
            if dry_run else "Backfill complete."
        ))

    # ── output helpers ────────────────────────────────────────────────
    def _section(self, title):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(title))

    def _line(self, label, value):
        self.stdout.write(f"  {label:<34} {value:>8}")

    def _mismatches(self, kind, rows):
        if not rows:
            return
        self.stdout.write(self.style.WARNING(
            f"  {len(rows)} entities have a stored {kind} that disagrees with "
            f"their parent chain."
        ))
        self.stdout.write(
            "  Left unchanged — the hierarchy is not automatically authoritative "
            "over a value someone set."
        )
        for row in rows[:20]:
            self.stdout.write(
                f"    {row['entity']}  stored={row['stored']}  derived={row['derived']}"
            )
        if len(rows) > 20:
            self.stdout.write(f"    ... and {len(rows) - 20} more")
