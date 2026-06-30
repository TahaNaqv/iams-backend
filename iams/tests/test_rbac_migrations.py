"""Regression tests for the RBAC data migrations and the seed command.

The pytest suite runs with --no-migrations (schema built from models), so
these call the migration functions directly against the live app registry to
exercise the 6→9 role remap (0036) and the department_entity backfill (0038),
plus seed_rbac idempotency.
"""
from __future__ import annotations

import importlib

import pytest
from django.apps import apps as global_apps
from django.contrib.auth import get_user_model
from django.core.management import call_command

from iams.models import (
    AuditableEntity,
    Module,
    Role,
    RoleModuleAccess,
    UserProfile,
)
from iams.rbac_matrix import LEGACY_ROLE_MAP, ROLE_MATRIX

User = get_user_model()

map_roles_mod = importlib.import_module("iams.migrations.0036_map_legacy_roles")
backfill_mod = importlib.import_module("iams.migrations.0038_backfill_department_entity")


def _legacy_user(role, username):
    u = User.objects.create_user(username=username, email=f"{username}@t.test", password="Pw123456!")
    UserProfile.objects.create(user=u, role=role, department="Finance", status="Active")
    return u


@pytest.mark.django_db
def test_role_remap_reassigns_profiles_and_preserves_super_admin():
    # Seed the legacy 6 roles + a user on each.
    legacy_names = list(LEGACY_ROLE_MAP.keys())
    users = {}
    for name in legacy_names:
        role = Role.objects.create(name=name, is_super_admin=(name == "Super Admin"))
        users[name] = _legacy_user(role, f"u_{name}".replace(" ", "_"))

    map_roles_mod.map_roles(global_apps, None)

    # All 9 canonical roles now exist.
    for canonical in set(LEGACY_ROLE_MAP.values()):
        assert Role.objects.filter(name=canonical).exists()
    # The 3 net-new roles too.
    for new_role in ["QA / quality reviewer", "Read-only stakeholder", "External auditor / regulator"]:
        assert Role.objects.filter(name=new_role).exists()

    # Each legacy user's profile now points at the mapped canonical role.
    for legacy_name, canonical in LEGACY_ROLE_MAP.items():
        profile = users[legacy_name].profile
        profile.refresh_from_db()
        assert profile.role.name == canonical

    # is_super_admin preserved on System administrator; issuance gate on Auditee.
    assert Role.objects.get(name="System administrator").is_super_admin is True
    assert Role.objects.get(name="Auditee / client manager").requires_issuance_gate is True

    # Legacy roles (that were renamed) are gone — except any whose name equals
    # its canonical mapping (none here).
    for legacy_name in legacy_names:
        if legacy_name not in ROLE_MATRIX:  # legacy names aren't canonical
            assert not Role.objects.filter(name=legacy_name).exists()


@pytest.mark.django_db
def test_department_entity_backfill_matches_case_insensitively():
    finance = AuditableEntity.objects.create(
        name="Finance", entity_type="Department", status="Active", risk_rating="Medium",
    )
    role = Role.objects.create(name="X")
    matched = User.objects.create_user(username="m", email="m@t.test", password="Pw123456!")
    UserProfile.objects.create(user=matched, role=role, department="finance", department_entity=None)
    unmatched = User.objects.create_user(username="n", email="n@t.test", password="Pw123456!")
    UserProfile.objects.create(user=unmatched, role=role, department="Nonexistent", department_entity=None)

    backfill_mod.backfill(global_apps, None)

    matched.profile.refresh_from_db()
    unmatched.profile.refresh_from_db()
    assert matched.profile.department_entity_id == finance.id  # case-insensitive match
    assert unmatched.profile.department_entity_id is None       # skip-and-log, no failure


@pytest.mark.django_db
def test_seed_rbac_is_idempotent():
    call_command("seed_rbac")
    call_command("seed_rbac")  # second run must not duplicate or error

    assert Module.objects.count() == 11
    # 9 canonical roles (seed may not delete legacy, but should create the 9).
    for name in ROLE_MATRIX:
        assert Role.objects.filter(name=name).exists()
    # Exactly one cell per (role, module) for canonical roles.
    for name in ROLE_MATRIX:
        role = Role.objects.get(name=name)
        assert role.module_access.count() == 11
    # Super admin user provisioned with the admin role.
    admin = Role.objects.get(name="System administrator")
    assert admin.is_super_admin is True
    assert UserProfile.objects.filter(role=admin).exists()
