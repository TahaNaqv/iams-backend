"""Factories for users, roles, permissions."""
from __future__ import annotations

import factory
from django.contrib.auth import get_user_model

from iams.models import Permission, Role, UserProfile

User = get_user_model()


class PermissionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Permission
        django_get_or_create = ("key",)

    key = factory.Sequence(lambda n: f"perm_{n}")
    name = factory.LazyAttribute(lambda o: o.key.replace("_", " ").title())
    module = "test"
    description = ""


class RoleFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Role
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Role {n}")
    is_super_admin = False

    @factory.post_generation
    def permissions(self, create, extracted, **kwargs):
        if not create:
            return
        if extracted:
            self.permissions.set(extracted)


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"user{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@iams.test")
    first_name = "Test"
    last_name = "User"
    is_active = True
    password = factory.PostGenerationMethodCall("set_password", "TestPassword123!")


class UserProfileFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = UserProfile

    user = factory.SubFactory(UserFactory)
    role = factory.SubFactory(RoleFactory)
    department = "Internal Audit"
    status = "Active"


class SuperAdminUserFactory(UserFactory):
    """A user with the Super Admin role attached."""

    @factory.post_generation
    def profile(self, create, extracted, **kwargs):
        if not create:
            return
        role = RoleFactory(name="Super Admin", is_super_admin=True)
        UserProfile.objects.create(user=self, role=role, department="Audit", status="Active")
