# Stage 2 of the Department → AuditableEntity merge.
#
# Introduces ``AuditableEntity.department_entity`` — a self-referential FK to
# the owning ``Department``-type entity — and backfills it from the merge
# nodes created in 0031. This is the tree-native replacement for the old
# ``department_ref`` FK (which pointed at the standalone ``Department`` model).
#
# Both columns coexist during the cutover: serializers/filters switch to
# ``department_entity`` here, and the legacy ``department_ref`` (plus the
# ``Department`` table) is dropped in a later migration once every consumer,
# frontend included, no longer reads it. Additive and reversible.

from django.db import migrations, models
import django.db.models.deletion

MERGE_SOURCE = "department-merge"


def backfill_department_entity(apps, schema_editor):
    AuditableEntity = apps.get_model("iams", "AuditableEntity")

    node_by_dept = {
        n.external_id: n.id
        for n in AuditableEntity.objects.filter(external_source=MERGE_SOURCE)
    }
    for entity in AuditableEntity.objects.exclude(department_ref_id=None):
        node_id = node_by_dept.get(str(entity.department_ref_id))
        if node_id is not None:
            entity.department_entity_id = node_id
            entity.save(update_fields=["department_entity"])


def noop_reverse(apps, schema_editor):
    # The column is removed by the schema reversal; nothing to undo in data.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("iams", "0031_merge_departments_into_entities"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditableentity",
            name="department_entity",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="member_entities",
                to="iams.auditableentity",
                help_text="Owning Department-type entity (replaces department_ref).",
            ),
        ),
        migrations.AddIndex(
            model_name="auditableentity",
            index=models.Index(
                fields=["department_entity", "status"],
                name="ae_dept_entity_status_idx",
            ),
        ),
        migrations.RunPython(backfill_department_entity, noop_reverse),
    ]
