"""Structured logging configuration (tasks.md T019, FR-002/FR-018).

Fetch/processing errors must be clearly attributable to the topic (and run)
they came from — one topic's failure must never blur into "something broke
somewhere." `TopicContextFilter` + the format string below put that context
in every log line without every call site having to repeat it.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_LOG_FORMAT = (
    "%(asctime)s %(levelname)-8s %(name)s "
    "[user=%(user_id)s topic=%(topic)s digest=%(digest_id)s] %(message)s"
)


class TopicContextFilter(logging.Filter):
    """Fills in user_id/topic/digest_id with '-' when a log call omits them,
    so the format string above never raises a KeyError on plain log calls."""

    def filter(self, record: logging.LogRecord) -> bool:
        for field in ("user_id", "topic", "digest_id"):
            if not hasattr(record, field):
                setattr(record, field, "-")
        return True


def configure_logging(level: int = logging.INFO) -> None:
    """Idempotent: safe to call multiple times (e.g. once per CLI invocation)."""
    root = logging.getLogger()
    root.setLevel(level)

    # Avoid duplicate handlers if called more than once in the same process.
    if any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        return

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    handler.addFilter(TopicContextFilter())
    root.addHandler(handler)


def get_logger(name: str, **context: Any) -> logging.LoggerAdapter:
    """A logger pre-bound with topic/digest/user context for a run.

    Usage: `log = get_logger(__name__, topic="AAPL", digest_id=digest.id)`
    then every `log.info(...)`/`log.error(...)` call carries that context.
    """
    return logging.LoggerAdapter(logging.getLogger(name), context)
