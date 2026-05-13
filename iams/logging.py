"""Structured logging for IAMS (Phase 5 Track 3).

One-line JSON per log record so Promtail can ship straight to Loki
without parsing. The formatter intentionally has no third-party
dependency (no python-json-logger) — keeping it inline means tests
can introspect the output without re-spawning the logging stack.

Fields emitted on every record:

  - ``time``: ISO-8601 UTC timestamp.
  - ``level``: standard log level name.
  - ``logger``: module logger name.
  - ``message``: the formatted message string.
  - ``request_id``: correlation id set by ``RequestIdMiddleware``;
    "-" outside a request.
  - ``service``: ``iams-backend`` (constant; identifies the producer).
  - ``env``: value of ``IAMS_LOG_ENV`` env var if set (e.g. "prod").
  - Any ``extra={...}`` kwargs from the caller are folded into the
    top level *unless* their key collides with the reserved set above,
    in which case the extra is dropped (silent — we don't want our
    own logging to throw).
  - ``exception``: full traceback as a single string when present.
"""
from __future__ import annotations

import json
import logging
import os
import socket
import traceback
from datetime import datetime, timezone

_RESERVED = {
    "time", "level", "logger", "message", "request_id", "service", "env",
    "exception", "host",
}
# Default LogRecord attributes that are *not* `extra` — exclude them
# when collecting user-supplied extra fields.
_LOGRECORD_DEFAULTS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "getMessage", "request_id",
}


class JsonFormatter(logging.Formatter):
    """Render every record as a single line of JSON."""

    SERVICE = "iams-backend"

    def __init__(self) -> None:
        super().__init__()
        self._env = os.environ.get("IAMS_LOG_ENV", "")
        self._host = socket.gethostname()

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "service": self.SERVICE,
            "host": self._host,
        }
        if self._env:
            payload["env"] = self._env

        # Fold user-supplied extra={} fields in.
        for key, value in record.__dict__.items():
            if key in _LOGRECORD_DEFAULTS or key in _RESERVED:
                continue
            try:
                json.dumps(value)
                payload[key] = value
            except (TypeError, ValueError):
                payload[key] = repr(value)

        if record.exc_info:
            payload["exception"] = "".join(
                traceback.format_exception(*record.exc_info)
            )

        try:
            return json.dumps(payload, default=str)
        except (TypeError, ValueError):
            # Last-resort: drop the dict and emit just the message
            # rather than failing the log call.
            return json.dumps(
                {
                    "time": payload["time"],
                    "level": payload["level"],
                    "logger": payload["logger"],
                    "message": str(record.getMessage()),
                    "request_id": payload["request_id"],
                    "service": payload["service"],
                    "_format_error": "payload not serializable",
                }
            )
