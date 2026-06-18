# Stage 1 of the Department → AuditableEntity merge.
#
# Additive and reversible. For every row in the standalone ``Department``
# table this creates a mirror ``AuditableEntity`` with
# ``entity_type="Department"`` and re-parents each top-level engagement
# (``department_ref`` set, ``parent`` null) under its department node, so the
# audit universe becomes a single self-nesting tree.
#
# Nothing is dropped here — the ``Department`` table and the ``department_ref``
# FKs remain intact. The final drop happens in a later migration once every
# consumer has been cut over. The merge nodes are tagged with
# ``external_source="department-merge"`` (and ``external_id`` = the source
# department UUID) so this migration is idempotent and fully reversible.

from django.db import migrations

MERGE_SOURCE = "department-merge"


def merge_departments_into_entities(apps, schema_editor):
    Department = apps.get_model("iams", "Department")
    AuditableEntity = apps.get_model("iams", "AuditableEntity")

    dept_to_node = {}
    for dept in Department.objects.all():
        # Idempotent: reuse a prior merge node, or an existing Department-type
        # entity carrying the same name; otherwise create a fresh node.
        node = AuditableEntity.objects.filter(
            external_source=MERGE_SOURCE, external_id=str(dept.id)
        ).first()
        if node is None:
            node = AuditableEntity.objects.filter(
                entity_type="Department", name=dept.name
            ).first()
            if node is not None:
                node.external_source = MERGE_SOURCE
                node.external_id = str(dept.id)
                node.save(update_fields=["external_source", "external_id"])
        if node is None:
            # Reuse the Department's UUID as the node PK so existing
            # ``department_ref`` values keep pointing at a valid row once the
            # FK is retargeted to AuditableEntity, and the frontend's
            # ``departmentId`` continues to resolve through the cutover.
            node = AuditableEntity.objects.create(
                id=dept.id,
                name=dept.name,
                entity_type="Department",
                risk_rating=dept.risk_rating,
                business_unit=dept.business_unit,
                last_audit_date=dept.last_audit_date,
                next_audit_date=dept.next_audit_date,
                department=dept.name,  # denormalized display string
                status="Active",
                external_source=MERGE_SOURCE,
                external_id=str(dept.id),
            )
        dept_to_node[str(dept.id)] = node

    # Re-parent each top-level engagement under its department node. We only
    # touch rows whose ``parent`` is still null so we never clobber an
    # existing hierarchy the user has already built.
    for entity in AuditableEntity.objects.exclude(entity_type="Department"):
        if entity.parent_id is not None or entity.department_ref_id is None:
            continue
        node = dept_to_node.get(str(entity.department_ref_id))
        if node is not None and node.pk != entity.pk:
            entity.parent = node
            entity.save(update_fields=["parent"])


def reverse(apps, schema_editor):
    AuditableEntity = apps.get_model("iams", "AuditableEntity")

    merge_node_ids = list(
        AuditableEntity.objects.filter(external_source=MERGE_SOURCE).values_list(
            "pk", flat=True
        )
    )
    # Detach engagements we re-parented, then delete the merge nodes.
    AuditableEntity.objects.filter(parent_id__in=merge_node_ids).update(parent=None)
    AuditableEntity.objects.filter(pk__in=merge_node_ids).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("iams", "0030_auditableentity_custom_fields"),
    ]

    operations = [
        migrations.RunPython(merge_departments_into_entities, reverse),
    ]
