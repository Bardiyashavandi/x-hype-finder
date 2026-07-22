"""Retry-with-backoff decorator for transient fetch/processing errors (tasks.md T020, FR-018).

Wrap a call with `@retry_with_backoff(...)`; after `max_attempts` failures the
last exception propagates so the caller can record it as a persistent
per-topic error (FR-002) rather than retry forever.
"""

from __future__ import annotations

import functools
import logging
import random
import time
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

R = TypeVar("R")


def retry_with_backoff(
    *,
    max_attempts: int = 3,
    base_delay_seconds: float = 1.0,
    backoff_factor: float = 2.0,
    jitter_seconds: float = 0.25,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    sleep: Callable[[float], None] | None = None,
) -> Callable[[Callable[..., R]], Callable[..., R]]:
    """Retry the decorated call up to `max_attempts` times on `exceptions`,
    waiting `base_delay_seconds * backoff_factor ** attempt` (+ small jitter,
    so concurrent retries don't stack in lockstep) between attempts.
    """
    if max_attempts < 1:
        raise ValueError("max_attempts must be >= 1")

    def decorator(func: Callable[..., R]) -> Callable[..., R]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> R:
            # Resolved on every call (not cached as a default parameter at
            # decoration time) so tests can monkeypatch `time.sleep` globally
            # even against a function decorated once at module-import time.
            effective_sleep = sleep if sleep is not None else time.sleep
            last_exc: BaseException | None = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:  # noqa: PERF203 - retry loop, not a hot path
                    last_exc = exc
                    is_last_attempt = attempt == max_attempts - 1
                    if is_last_attempt:
                        logger.error(
                            "%s failed after %d attempt(s), giving up: %s",
                            func.__qualname__,
                            max_attempts,
                            exc,
                        )
                        raise
                    delay = base_delay_seconds * (backoff_factor**attempt)
                    delay += random.uniform(0, jitter_seconds)
                    logger.warning(
                        "%s failed (attempt %d/%d): %s — retrying in %.2fs",
                        func.__qualname__,
                        attempt + 1,
                        max_attempts,
                        exc,
                        delay,
                    )
                    effective_sleep(delay)
            # Unreachable: the loop above always either returns or raises.
            raise last_exc  # pragma: no cover

        return wrapper

    return decorator
