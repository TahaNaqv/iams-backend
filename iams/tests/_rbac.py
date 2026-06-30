"""Shared test helpers for seeding the Role Access Matrix.

Used by conftest fixtures and any TestCase that builds roles directly, so the
new matrix-backed ``HasPermission`` shim resolves correctly. Cells are derived
from a legacy permission-key set, reproducing the pre-matrix effective access.
"""
from __future__ import annotations

from iams.models import Module, RoleModuleAccess
from iams.rbac_matrix import (
    ACCESS_RANK,
    LEGACY_PERMISSION_MAP,
    MODULE_KEYS,
    MODULES,
    NONE,
    READ,
)


def ensure_modules() -> dict[str, Module]:
    """Idempotently create the 11 matrix modules; return {key: Module}."""
    mods: dict[str, Module] = {}
    for key, name, order in MODULES:
        mods[key], _ = Module.objects.get_or_create(
            key=key, defaults={"name": name, "order": order}
        )
    return mods


def cells_from_keys(perm_keys) -> dict[str, str]:
    """Map a legacy permission-key set to {module_key: level} (highest level
    wins per module)."""
    levels = {key: NONE for key in MODULE_KEYS}
    for key in perm_keys:
        mapping = LEGACY_PERMISSION_MAP.get(key)
        if not mapping:
            continue
        module, level = mapping
        if ACCESS_RANK.get(level, 1) > ACCESS_RANK.get(levels[module], 1):
            levels[module] = level
    # Legacy "audits" keys (view/create/edit/delete_audits) were an umbrella
    # that governed the whole audit surface — what the matrix now splits into
    # audit_plan, audit_universe, risk_assessment, workpapers and engagements.
    # Mirror the engagements level into those modules so legacy-derived fixture
    # roles retain the same effective access they had before the split.
    eng = levels["engagements"]
    for module in ("audit_plan", "audit_universe", "risk_assessment", "workpapers"):
        if ACCESS_RANK.get(eng, 1) > ACCESS_RANK.get(levels[module], 1):
            levels[module] = eng
    # Dashboards were previously visible to any authenticated user (the
    # dashboard endpoints used IsAuthenticated). Give legacy-derived roles at
    # least read on dashboards if they have any audit/report access, so the
    # legacy endpoint tests keep their old effective access.
    if (
        ACCESS_RANK.get(eng, 1) >= ACCESS_RANK.get(READ, 2)
        or ACCESS_RANK.get(levels["reports"], 1) >= ACCESS_RANK.get(READ, 2)
    ):
        if ACCESS_RANK.get(levels["dashboards"], 1) < ACCESS_RANK.get(READ, 2):
            levels["dashboards"] = READ
    return levels


def seed_role_matrix(role, perm_keys) -> None:
    """Seed RoleModuleAccess cells for ``role`` from a legacy key set."""
    mods = ensure_modules()
    for module_key, level in cells_from_keys(perm_keys).items():
        RoleModuleAccess.objects.update_or_create(
            role=role, module=mods[module_key], defaults={"level": level}
        )


def seed_canonical_roles():
    """Create the real 9 matrix roles with their exact cells. Returns
    {role_name: Role}. Mirrors what migrations + seed_rbac produce, for use
    in tests that validate the true matrix (not the legacy 6-role fixtures)."""
    from iams.models import Role
    from iams.rbac_matrix import ROLE_MATRIX, ROLE_META

    mods = ensure_modules()
    roles = {}
    for name, (description, is_super_admin, gate) in ROLE_META.items():
        role = Role.objects.create(
            name=name,
            description=description,
            is_super_admin=is_super_admin,
            requires_issuance_gate=gate,
        )
        for module_key, (level, scoped) in ROLE_MATRIX[name].items():
            RoleModuleAccess.objects.create(
                role=role, module=mods[module_key], level=level, scoped=scoped
            )
        roles[name] = role
    return roles
