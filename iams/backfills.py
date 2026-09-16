"""One-time data backfills for the Audit Universe v2 migration.

Each backfill is written once here and driven from two places:

* migrations ``0050``-``0053``, which pass **historical** model classes from
  ``apps.get_model`` so a fresh install or a small database is fixed up by a
  plain ``migrate``;
* ``manage.py backfill_audit_universe``, which passes the **real** model
  classes and adds ``--dry-run`` and reporting, so a large production
  universe can be done deliberately in a maintenance window before the
  deploy — after which the migrations find nothing to do and pass in
  milliseconds.

Every function is **idempotent**: re-running changes nothing and returns a
report with zero counts. That matters because the manual run and the
migration run will both happen, in that order, against the same rows.

None of these functions overwrite a value a human set. They fill blanks, and
where a derived value disagrees with a stored one they *report* the
disagreement rather than silently correcting it — a wrong business unit is a
conversation with the audit team, not something a deploy should decide.
"""
from __future__ import annotations

import logging
import re
from datetime import date

logger = logging.getLogger(__name__)

# Literals rather than imports from ``iams.models``. A backfill has to keep
# meaning what it meant on the day it was written, even if the enums later
# gain or rename members.
DEPARTMENT_TYPE = "Department"

# Code prefixes, most specific source first: the universe category, then the
# entity type, then a generic fallback.
CATEGORY_PREFIXES = {
    "Governance": "GOV",
    "Operations": "OPS",
    "Finance": "FIN",
    "IT": "IT",
    "Compliance": "CMP",
    "Support": "SUP",
    "Process": "PRC",
    "Advisory": "ADV",
    "ThirdParty": "TPT",
}
ENTITY_TYPE_PREFIXES = {
    "Process": "PRC",
    "Department": "DEP",
    "Division": "DIV",
    "Area": "ARE",
    "System": "SYS",
    "Function": "FUN",
    "Project": "PRJ",
    "ComplianceArea": "CMP",
    "LegalEntity": "LEG",
    "Branch": "BRN",
    "Program": "PRG",
    "RiskArea": "RSK",
    "ThirdParty": "TPT",
    "Application": "APP",
}
FALLBACK_PREFIX = "AE"
CODE_PATTERN = re.compile(r"^([A-Z]{2,4})-(\d+)$")
CODE_DIGITS = 4


def _entity_manager(Entity):
    """The manager that sees every row, archived included.

    The real ``AuditableEntity.objects`` is an active manager that hides
    archived rows; historical models built by ``apps.get_model`` carry only a
    plain manager and so do not. Archived entities still need codes —
    migration ``0055`` makes ``code`` required for every row — so both the read
    *and the write* paths must go through this. Using ``Entity.objects`` for a
    ``bulk_update`` silently skips archived rows, which then fail the NOT NULL
    check in 0055 with nothing in the logs to explain it.
    """
    return getattr(Entity, "all_objects", None) or Entity.objects


def _all_entities(Entity):
    """Every row, archived included."""
    return _entity_manager(Entity).all()


# ══════════════════════════════════════════════════════════════════════
# 0050 — entity codes
# ══════════════════════════════════════════════════════════════════════
def _prefix_for(entity) -> str:
    category = (getattr(entity, "universe_category", "") or "").strip()
    if category in CATEGORY_PREFIXES:
        return CATEGORY_PREFIXES[category]
    entity_type = (getattr(entity, "entity_type", "") or "").strip()
    return ENTITY_TYPE_PREFIXES.get(entity_type, FALLBACK_PREFIX)


def backfill_entity_codes(Entity, *, dry_run: bool = False, batch_size: int = 500) -> dict:
    """Give every entity without one a human-readable register reference.

    Codes look like ``OPS-0042``: a prefix from the universe category (falling
    back to the entity type, then ``AE``) and a per-prefix sequence.

    Sequences continue from the highest number already in use for that prefix,
    so codes an administrator typed by hand are never renumbered and a second
    run allocates nothing. Rows are processed in ``(created_at, id)`` order so
    the same database always produces the same codes.
    """
    taken: set[str] = set()
    next_seq: dict[str, int] = {}
    for existing in (
        _all_entities(Entity).exclude(code="").values_list("code", flat=True)
    ):
        taken.add(existing)
        match = CODE_PATTERN.match(existing)
        if match:
            prefix, number = match.group(1), int(match.group(2))
            next_seq[prefix] = max(next_seq.get(prefix, 0), number)

    pending = list(
        _all_entities(Entity)
        .filter(code="")
        .order_by("created_at", "id")
        .only("id", "code", "universe_category", "entity_type", "created_at")
    )

    assigned: list = []
    report = {"scanned": len(pending), "assigned": 0, "by_prefix": {}}
    for entity in pending:
        prefix = _prefix_for(entity)
        # Skip over any number already taken by a hand-written code.
        while True:
            next_seq[prefix] = next_seq.get(prefix, 0) + 1
            candidate = f"{prefix}-{next_seq[prefix]:0{CODE_DIGITS}d}"
            if candidate not in taken:
                break
        taken.add(candidate)
        entity.code = candidate
        assigned.append(entity)
        report["assigned"] += 1
        report["by_prefix"][prefix] = report["by_prefix"].get(prefix, 0) + 1

    if assigned and not dry_run:
        writer = _entity_manager(Entity)
        for start in range(0, len(assigned), batch_size):
            writer.bulk_update(
                assigned[start:start + batch_size], ["code"], batch_size=batch_size,
            )
    logger.info("backfill_entity_codes: %s", report)
    return report


# ══════════════════════════════════════════════════════════════════════
# 0051 — structural links derived from the hierarchy
# ══════════════════════════════════════════════════════════════════════
def derive_structural_links(Entity, *, dry_run: bool = False, batch_size: int = 500) -> dict:
    """Fill blank ``department_entity`` / ``business_unit`` from the ancestors.

    In v2 the form asks only for a parent; the owning department is the nearest
    ``Department``-type ancestor and the business unit is the nearest ancestor
    that has one. Until now both could also be set directly, which is how the
    same entity could end up with a ``department_entity`` FK saying one thing
    and its parent chain saying another.

    This **only fills blanks**. Where a stored value disagrees with what the
    hierarchy implies, the row is reported and left alone — picking a winner is
    a decision for the audit team, not for a deploy.

    Cycle-guarded: a corrupted parent loop terminates instead of hanging.
    """
    rows = {
        row.pk: row
        for row in _all_entities(Entity).only(
            "id", "parent_id", "entity_type", "business_unit_id", "department_entity_id",
        )
    }

    def ancestors(entity):
        seen: set = set()
        node = rows.get(entity.parent_id)
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            yield node
            node = rows.get(node.parent_id)

    report = {
        "scanned": len(rows),
        "department_filled": 0,
        "business_unit_filled": 0,
        "department_mismatches": [],
        "business_unit_mismatches": [],
    }
    to_update: list = []

    for entity in rows.values():
        if entity.parent_id is None:
            # A root has nothing to inherit from; whatever it carries stands.
            continue
        derived_department = None
        derived_business_unit = None
        for node in ancestors(entity):
            if derived_department is None and node.entity_type == DEPARTMENT_TYPE:
                derived_department = node.pk
            if derived_business_unit is None and node.business_unit_id:
                derived_business_unit = node.business_unit_id
            if derived_department and derived_business_unit:
                break

        dirty = []
        if derived_department:
            if entity.department_entity_id is None:
                entity.department_entity_id = derived_department
                dirty.append("department_entity")
                report["department_filled"] += 1
            elif entity.department_entity_id != derived_department:
                report["department_mismatches"].append({
                    "entity": str(entity.pk),
                    "stored": str(entity.department_entity_id),
                    "derived": str(derived_department),
                })
        if derived_business_unit:
            if entity.business_unit_id is None:
                entity.business_unit_id = derived_business_unit
                dirty.append("business_unit")
                report["business_unit_filled"] += 1
            elif entity.business_unit_id != derived_business_unit:
                report["business_unit_mismatches"].append({
                    "entity": str(entity.pk),
                    "stored": str(entity.business_unit_id),
                    "derived": str(derived_business_unit),
                })
        if dirty:
            to_update.append(entity)

    if to_update and not dry_run:
        writer = _entity_manager(Entity)
        for start in range(0, len(to_update), batch_size):
            writer.bulk_update(
                to_update[start:start + batch_size],
                ["department_entity", "business_unit"],
                batch_size=batch_size,
            )
    logger.info(
        "derive_structural_links: filled dept=%d bu=%d; mismatches dept=%d bu=%d",
        report["department_filled"], report["business_unit_filled"],
        len(report["department_mismatches"]), len(report["business_unit_mismatches"]),
    )
    return report


# ══════════════════════════════════════════════════════════════════════
# 0052 — legacy size columns into the materiality registry
# ══════════════════════════════════════════════════════════════════════
# Legacy column -> metric definition code.
LEGACY_METRIC_MAP = {
    "headcount": "headcount",
    "operating_budget": "annual_expenses",
}


def migrate_materiality_values(
    Entity, MetricDef, MaterialityValue, *, dry_run: bool = False, as_of: date | None = None,
) -> dict:
    """Move ``headcount`` and ``operating_budget`` into the metric registry.

    ``as_of`` records **when the figure was migrated**, not the period it
    describes — the legacy columns never carried a period. ``source`` says so,
    so nobody later mistakes the migration date for a reporting date.

    Idempotent by ``(entity, definition)`` rather than by period: once an
    entity has any value for a metric, this leaves it alone. Guarding on the
    period instead would create a fresh duplicate row on every day the backfill
    was re-run.
    """
    as_of = as_of or date.today()
    definitions = {
        d.code: d for d in MetricDef.objects.filter(code__in=set(LEGACY_METRIC_MAP.values()))
    }
    report = {"created": 0, "skipped_existing": 0, "missing_definitions": []}
    missing = set(LEGACY_METRIC_MAP.values()) - set(definitions)
    if missing:
        # 0049 seeds these. If they are gone, an administrator deleted them and
        # we must not silently re-create them under a different id.
        report["missing_definitions"] = sorted(missing)
        logger.warning(
            "migrate_materiality_values: metric definitions missing, skipping: %s",
            report["missing_definitions"],
        )

    already = set(
        MaterialityValue.objects
        .filter(definition__code__in=set(LEGACY_METRIC_MAP.values()))
        .values_list("entity_id", "definition__code")
    )

    to_create = []
    for entity in _all_entities(Entity).only("id", "headcount", "operating_budget"):
        for column, metric_code in LEGACY_METRIC_MAP.items():
            definition = definitions.get(metric_code)
            if definition is None:
                continue
            value = getattr(entity, column, None)
            if value is None:
                continue
            if (entity.pk, metric_code) in already:
                report["skipped_existing"] += 1
                continue
            to_create.append(MaterialityValue(
                entity_id=entity.pk,
                definition=definition,
                value=value,
                as_of=as_of,
                source=f"Migrated from legacy {column} column; period not recorded.",
            ))
            report["created"] += 1

    if to_create and not dry_run:
        MaterialityValue.objects.bulk_create(to_create, batch_size=500)
    logger.info("migrate_materiality_values: %s", report)
    return report


# ══════════════════════════════════════════════════════════════════════
# 0053 — inherent likelihood/impact into the risk register
# ══════════════════════════════════════════════════════════════════════
MIGRATED_RISK_TITLE = "Migrated inherent assessment"


def migrate_inherent_risk_to_register(
    Entity, EntityRisk, *, dry_run: bool = False,
) -> dict:
    """Preserve entity-level inherent likelihood/impact as a register entry.

    Those two columns stop being form inputs in v2 — assessments are entered as
    ``EntityRisk`` line items with controls and a residual position. Before the
    inputs disappear, any entity that carries a bare inherent pair and has no
    risks at all gets one risk row recording it, so the judgement someone made
    is not stranded on a field nobody edits any more.

    Only entities with **zero** risks are touched: if a register already
    exists, the roll-up is already the authority and inventing an extra row
    would distort it.

    Rows are written with ``bulk_create``, which does not fire ``post_save``.
    That is deliberate — the ``EntityRisk`` signal would re-roll each entity's
    position, and a backfill whose job is to preserve the current position must
    not change ratings on its way past.
    """
    candidates = list(
        _all_entities(Entity)
        .filter(inherent_likelihood__isnull=False, inherent_impact__isnull=False)
        .only("id", "inherent_likelihood", "inherent_impact")
    )
    if not candidates:
        return {"scanned": 0, "created": 0, "skipped_has_risks": 0}

    candidate_ids = [e.pk for e in candidates]
    with_risks = set(
        EntityRisk.objects.filter(entity_id__in=candidate_ids)
        .values_list("entity_id", flat=True)
    )

    to_create = []
    report = {"scanned": len(candidates), "created": 0, "skipped_has_risks": 0}
    for entity in candidates:
        if entity.pk in with_risks:
            report["skipped_has_risks"] += 1
            continue
        to_create.append(EntityRisk(
            entity_id=entity.pk,
            title=MIGRATED_RISK_TITLE,
            description=(
                "Carried over from the entity's inherent likelihood and impact "
                "fields when the audit universe moved to a risk-register-driven "
                "assessment. The original rating was recorded before controls "
                "were documented, so no residual position or control "
                "effectiveness is claimed here. Review and replace with real "
                "risks at the next assessment."
            ),
            category="Operational",
            inherent_likelihood=entity.inherent_likelihood,
            inherent_impact=entity.inherent_impact,
            existing_controls="",
            control_effectiveness="Not Assessed",
            # Left unset so the roll-up falls back to inherent rather than
            # asserting a post-control position nobody assessed.
            residual_likelihood=None,
            residual_impact=None,
            risk_response="Mitigate",
            status="Open",
        ))
        report["created"] += 1

    if to_create and not dry_run:
        EntityRisk.objects.bulk_create(to_create, batch_size=500)
    logger.info("migrate_inherent_risk_to_register: %s", report)
    return report
