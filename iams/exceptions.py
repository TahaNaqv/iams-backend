"""IAMS-wide exception handling.

The frontend's ``getApiErrorMessage`` normalizer accepts three shapes:
    - ``{"detail": "human-readable message"}``
    - ``{"message": "human-readable message"}``
    - ``{"<field>": ["error", ...]}``

DRF's default exception handler already produces (1) and (3); we extend it
to add request-id correlation and to log unexpected exceptions at ERROR
level so they reach Sentry/Loki without losing context.
"""
from __future__ import annotations

import logging
from typing import Any

from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler

from iams.middleware import get_current_request_id

logger = logging.getLogger(__name__)


def iams_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Custom exception handler.

    - Calls DRF's default handler for known exceptions.
    - Adds the current request_id to the payload for client-side correlation.
    - Logs unexpected exceptions (500-class) at ERROR with request_id.
    """
    response = drf_default_handler(exc, context)
    request_id = get_current_request_id()

    if response is None:
        # Unhandled exception → DRF returns None and lets Django render 500.
        logger.exception(
            "Unhandled exception in view",
            extra={"request_id": request_id, "view": context.get("view")},
        )
        return None

    if isinstance(response.data, dict):
        response.data.setdefault("requestId", request_id)

    return response
