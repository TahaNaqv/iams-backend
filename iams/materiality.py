"""Materiality metric values and the denormalised sort cache.

``EntityMaterialityValue`` is the source of truth: one row per
(entity, metric, period), carrying the figure and where it came from.
``AuditableEntity.materiality_cache`` mirrors the **latest** value per metric
as a flat ``{metric_code: number}`` map so the register can sort and
range-filter on "revenue" or "headcount" without a correlated subquery per
row. Postgres has a GIN index over it (see migration 0047).

The cache is derived and disposable. If it ever drifts, rebuild it:

    manage.py rebuild_materiality_cache

Nothing reads the cache for correctness — reports and the scoring
auto-suggestions read the rows. It exists only to make the list view fast.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)


def _to_number(value):
    """JSON-safe numeric for the cache, or ``None`` when not representable.

    Decimals are emitted as float because the cache is only ever compared and
    ordered, never summed into a reported figure — the exact Decimal stays on
    ``EntityMaterialityValue.value``.
    """
    if value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, TypeError, ValueError):
        return None


def build_materiality_cache(entity) -> dict:
    """Compute the ``{metric_code: number}`` map for one entity.

    Takes the most recent ``as_of`` per metric. Inactive metric definitions are
    still included: deactivating a metric hides it from the form, but a figure
    already captured against it should not silently vanish from a saved sort
    or a filter someone bookmarked.
    """
    latest: dict[str, tuple] = {}
    rows = (
        entity.materiality_values
        .select_related("definition")
        .order_by("definition__code", "-as_of")
    )
    for row in rows:
        code = row.definition.code
        # Rows arrive newest-first within each code, so the first one wins.
        if code in latest:
            continue
        number = _to_number(row.value)
        if number is not None:
            latest[code] = (number, row.as_of)
    return {code: number for code, (number, _as_of) in latest.items()}


def refresh_materiality_cache(entity, *, save: bool = True) -> dict:
    """Recompute and persist ``entity.materiality_cache``.

    Writes with ``update_fields`` so it never bumps ``version`` or trips the
    optimistic-locking check — refreshing a derived cache is not a user edit
    and must not make a concurrent PATCH fail with a spurious 409.
    """
    cache = build_materiality_cache(entity)
    if cache == entity.materiality_cache:
        return cache
    entity.materiality_cache = cache
    if save:
        type(entity).all_objects.filter(pk=entity.pk).update(materiality_cache=cache)
    return cache


def rebuild_all(*, batch_size: int = 500) -> int:
    """Rebuild the cache for every entity. Returns the number changed.

    Batched so a large universe does not hold one long transaction open.
    """
    from iams.models import AuditableEntity

    changed = 0
    qs = (
        AuditableEntity.all_objects
        .prefetch_related("materiality_values__definition")
        .order_by("pk")
    )
    start = 0
    while True:
        chunk = list(qs[start:start + batch_size])
        if not chunk:
            break
        for entity in chunk:
            before = entity.materiality_cache
            after = build_materiality_cache(entity)
            if before != after:
                AuditableEntity.all_objects.filter(pk=entity.pk).update(
                    materiality_cache=after,
                )
                changed += 1
        start += batch_size
    logger.info("materiality: rebuilt cache, %d entities changed", changed)
    return changed
