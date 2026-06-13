# IAMS Migration Checklist

Every migration that lands on `main` is auto-applied to staging on the next deploy, and to production on the next promote. The blue-green deploy runs `python manage.py migrate` **inside the new color's container before traffic flips**, so a broken migration aborts the deploy with the *old* color still serving. That safety net only works if the migration is **backward-compatible** with the *old* code that's still running during the cut-over window.

Run this checklist before merging any PR that adds or changes a migration.

## ✅ The N-1 rule

The currently-deployed app (color *N-1*) must keep working against the *new* schema, and the new app (color *N*) must keep working against the *old* data shape. Practically:

- A migration may **add** anything (column, table, index, constraint) with safe defaults.
- A migration may **drop** anything *only* once every running version of the app has stopped using it.
- A migration may **rename** by introducing the new name first, dual-writing for a release, then dropping the old name in a follow-up release.

## ✅ Adding a NOT NULL column

```python
# ❌ Don't:  fails on old rows; locks the table for the rewrite.
operations = [migrations.AddField("Audit", "phase", models.CharField(max_length=20))]

# ✅ Do:  ship in three steps across two releases.
# Release 1 — make the field nullable, default to a value the old code ignores.
operations = [
    migrations.AddField(
        "Audit", "phase",
        models.CharField(max_length=20, null=True, default=""),
    ),
]
# Release 2 — backfill via a data migration, then alter to NOT NULL.
operations = [
    migrations.RunPython(_backfill_phase, reverse_code=migrations.RunPython.noop),
    migrations.AlterField(
        "Audit", "phase",
        models.CharField(max_length=20),  # NOT NULL implicit
    ),
]
```

## ✅ Renaming a column

Same three-step dance:

1. Add the new column, dual-write from app code in a release.
2. Backfill via data migration.
3. Drop the old column once no live process reads it.

Never `RenameField` in production — it locks the table on Postgres < 11 and breaks any old worker still running the prior code.

## ✅ Adding an index on a populated table

```python
# ✅ Postgres-friendly — won't block writes on a large table.
class Migration(migrations.Migration):
    atomic = False
    operations = [
        migrations.AddIndex(
            model_name="finding",
            index=models.Index(
                fields=["department", "status"],
                name="iams_finding_dept_status_idx",
            ),
        ),
    ]
```

The `atomic = False` + Postgres "CREATE INDEX CONCURRENTLY" path is the only safe way to index a hot table. For tables < 1M rows, the default atomic mode is fine.

## ✅ Removing a model / table

1. Stop using the model in code (no imports, no admin registration).
2. Ship that change.
3. In the *next* release, drop the table with `DeleteModel`.

The intervening release ensures any running worker that still has the import statement won't crash.

## ✅ Data migrations

- Always pair with a `reverse_code` — even if it's just `migrations.RunPython.noop`. The blue-green script's automatic rollback path needs migrations to be reversible.
- Process in chunks for large tables (`.iterator(chunk_size=1000)`).
- Never call `model.save()` on the app's *current* model class from inside a data migration — use `apps.get_model("iams", "Finding")` so the migration uses the schema-at-time-of-write.

## ✅ Constraints, unique indexes

- Add as `not_valid`-style if the table has skew; validate in a follow-up migration.
- Partial unique constraints (Phase 3+ pattern in IAMS) are safe because they don't backfill against existing rows.

## ✅ Pre-merge gate

The CI workflow runs `manage.py makemigrations --check --dry-run --no-input` on every PR. If the model changed and the migration is missing, the build fails. A green CI is a necessary but not sufficient condition — this checklist is the rest.

## ✅ Rollback procedure

If a deploy fails after `migrate`:

1. The blue-green script leaves the *old* color live (it never flipped the symlink).
2. To revert the schema, run `python manage.py migrate iams <previous_migration>` inside the *old* color.
3. If the migration is irreversible (data migration with `noop` reverse), the schema stays at the new state; the old code must tolerate the new state — which is exactly what the N-1 rule guarantees.

## ✅ Authoring tips

- Inspect SQL with `python manage.py sqlmigrate iams 0019_perf_indexes_phase5`.
- For Postgres-only features (partial indexes, expression indexes, immutability triggers), gate them on `connection.vendor == "postgresql"` in a `RunSQL` operation so SQLite test runs still pass.
- Bigger schema changes warrant a `docs/migrations/<NNNN>-<slug>.md` entry explaining the *why* — the migration file itself is rarely enough.

---

Anything that doesn't fit a row above? Ask in `#iams-platform` before merging.
