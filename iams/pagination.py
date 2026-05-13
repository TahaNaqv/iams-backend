"""Pagination classes for the IAMS API.

DefaultPagination is wired as the DRF default. Endpoints that need a different
shape (cursor pagination for the audit log, large-page pagination for exports)
can override per-ViewSet.
"""
from __future__ import annotations

from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.response import Response


class DefaultPagination(PageNumberPagination):
    """Page-number pagination with sensible defaults.

    Query params:
        - ?page=N
        - ?page_size=N (capped at max_page_size)

    Phase 5 Track 2 tightened the default from 100 → 25 to keep the
    typical list response light (NFR-Performance, p95 < 500ms target).
    Tables that need a denser view pass ``?page_size=`` up to the
    ``max_page_size`` ceiling of 200.
    """

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200

    def get_paginated_response(self, data):
        return Response(
            {
                "count": self.page.paginator.count,
                "next": self.get_next_link(),
                "previous": self.get_previous_link(),
                "page": self.page.number,
                "pageSize": self.get_page_size(self.request),
                "totalPages": self.page.paginator.num_pages,
                "results": data,
            }
        )


class LargeResultsPagination(PageNumberPagination):
    """For export endpoints where larger pages are appropriate."""

    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000


class AuditLogCursorPagination(CursorPagination):
    """Cursor pagination for the audit log — stable across inserts."""

    page_size = 50
    max_page_size = 200
    ordering = "-created_at"
