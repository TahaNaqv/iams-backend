"""Factory Boy factories for IAMS models.

Used by tests to build model instances without hand-writing setup boilerplate.
Import like:

    from iams.tests.factories import AuditFactory, FindingFactory
"""
from __future__ import annotations

from .audits import (
    AuditFactory,
    CheckListItemFactory,
    CorrectiveActionFactory,
    DepartmentFactory,
    FindingFactory,
)
from .users import (
    PermissionFactory,
    RoleFactory,
    SuperAdminUserFactory,
    UserFactory,
    UserProfileFactory,
)

__all__ = [
    "AuditFactory",
    "CheckListItemFactory",
    "CorrectiveActionFactory",
    "DepartmentFactory",
    "FindingFactory",
    "PermissionFactory",
    "RoleFactory",
    "SuperAdminUserFactory",
    "UserFactory",
    "UserProfileFactory",
]
