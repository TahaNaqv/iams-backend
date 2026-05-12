"""Reusable model mixins and managers.

Wired into models gradually — adding the mixin is a no-op at the schema
level until a migration adds the underlying fields. Phase 2 will add
``SoftDeleteMixin`` to the user-facing tables (Audit, Finding,
CorrectiveAction, ManagedDocument, etc.) with a single migration.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone


class SoftDeleteQuerySet(models.QuerySet):
    """QuerySet that hides soft-deleted rows by default.

    Use ``.with_deleted()`` to opt back in or ``.only_deleted()`` to inspect
    the trash. ``.delete()`` flips the flag instead of actually deleting;
    ``.hard_delete()`` removes for real.
    """

    def delete(self):
        return self.update(is_deleted=True, deleted_at=timezone.now())

    def hard_delete(self):
        return super().delete()

    def with_deleted(self):
        return self.__class__(self.model, using=self._db).all()

    def only_deleted(self):
        return self.__class__(self.model, using=self._db).filter(is_deleted=True)


class SoftDeleteManager(models.Manager):
    """Manager that hides soft-deleted rows by default."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=False)

    def with_deleted(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self.model, using=self._db)

    def only_deleted(self) -> SoftDeleteQuerySet:
        return SoftDeleteQuerySet(self.model, using=self._db).filter(is_deleted=True)


class SoftDeleteMixin(models.Model):
    """Adds is_deleted / deleted_at columns and routes ``delete()`` through them.

    Default manager (``objects``) hides deleted rows. ``all_objects`` exposes
    everything for admin/audit needs.
    """

    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = SoftDeleteManager()
    all_objects = models.Manager()

    class Meta:
        abstract = True

    def delete(self, using=None, keep_parents=False):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        self.save(update_fields=["is_deleted", "deleted_at"], using=using)

    def hard_delete(self, using=None, keep_parents=False):
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self) -> None:
        self.is_deleted = False
        self.deleted_at = None
        self.save(update_fields=["is_deleted", "deleted_at"])
