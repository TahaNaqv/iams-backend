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

    The default page size is intentionally generous (100) because the current
    UI does not yet expose pagination controls on most list views. Phase 4's
    dashboard work will introduce proper paginated tables; at that point this
    default can be tightened to 25. The hard ceiling (``max_page_size``) is
    what determines the worst case, not this default.
    """

    page_size = 100
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
