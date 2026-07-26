"""Jittered publish timing + rolling-24h/5-post cap enforcement (tasks.md
T061, FR-014, FR-022, data-model.md § PostingMode Validation).

Two independent gates, both checked before any autonomous publish attempt
(src/posting/publish.py):

- The rolling-24h cap counts *actually published* autonomous posts
  (`DraftPost.status = published_auto`) in the trailing 24h window — a draft
  that only cleared the confidence threshold doesn't count until it
  publishes.
- The jitter gate recomputes a randomized "earliest next publish" moment
  from `PostingMode.last_post_published_at` on every check, rather than
  persisting a single fixed target — this needs no new schema field and
  still yields genuinely varied real-world gaps, since only a check that
  actually *passes* results in a publish (and thus a new
  `last_post_published_at`); a check that fails changes nothing, so redrawing
  jitter on the next check doesn't distort the observed spacing between
  publishes (SC-008: gaps must vary, never a fixed cadence).
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.orm import Session

from src.db.scoped import scoped_select
from src.models.draft_post import DraftPost, DraftPostStatus
from src.models.posting_mode import PostingMode

RATE_CAP_POSTS_PER_ROLLING_WINDOW = 5
ROLLING_WINDOW = timedelta(hours=24)

# MVP-tunable jitter bounds (spec.md Assumptions treats exact autonomous-
# posting parameters as implementation-tuned, same as confidence_threshold):
# wide enough to never look like a fixed cadence, narrow enough that a
# cleared-threshold draft doesn't sit for unreasonably long.
JITTER_MIN_INTERVAL = timedelta(minutes=30)
JITTER_MAX_INTERVAL = timedelta(hours=4)


class RandomLike(Protocol):
    def uniform(self, a: float, b: float) -> float: ...


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def count_autonomous_posts_in_rolling_window(
    session: Session, user_id, *, now: datetime | None = None
) -> int:
    """How many `published_auto` posts this user has in the trailing 24h (FR-022)."""
    effective_now = now if now is not None else datetime.now(UTC)
    window_start = effective_now - ROLLING_WINDOW
    rows = (
        session.execute(
            scoped_select(DraftPost, user_id).where(
                DraftPost.status == DraftPostStatus.PUBLISHED_AUTO,
                DraftPost.published_at >= window_start,
            )
        )
        .scalars()
        .all()
    )
    return len(rows)


def has_rate_cap_headroom(session: Session, user_id, *, now: datetime | None = None) -> bool:
    return (
        count_autonomous_posts_in_rolling_window(session, user_id, now=now)
        < RATE_CAP_POSTS_PER_ROLLING_WINDOW
    )


def compute_next_allowed_publish_time(
    last_post_published_at: datetime | None,
    *,
    now: datetime | None = None,
    rand: RandomLike = random,
) -> datetime:
    """The earliest moment the next autonomous post may go out — jittered
    (FR-014), never a fixed offset. No prior post means no gap to enforce."""
    effective_now = now if now is not None else datetime.now(UTC)
    if last_post_published_at is None:
        return effective_now
    jitter_seconds = rand.uniform(
        JITTER_MIN_INTERVAL.total_seconds(), JITTER_MAX_INTERVAL.total_seconds()
    )
    return _as_aware(last_post_published_at) + timedelta(seconds=jitter_seconds)


def can_publish_now(
    session: Session,
    posting_mode: PostingMode,
    user_id,
    *,
    now: datetime | None = None,
    rand: RandomLike = random,
) -> tuple[bool, str | None]:
    """Both gates combined — returns `(allowed, blocking_reason)`."""
    effective_now = now if now is not None else datetime.now(UTC)

    if not has_rate_cap_headroom(session, user_id, now=effective_now):
        return (
            False,
            f"rolling 24h autonomous-post cap reached ({RATE_CAP_POSTS_PER_ROLLING_WINDOW} posts)",
        )

    next_allowed = compute_next_allowed_publish_time(
        posting_mode.last_post_published_at, now=effective_now, rand=rand
    )
    if effective_now < next_allowed:
        return (
            False,
            f"jittered publish gate not yet elapsed (next allowed at {next_allowed.isoformat()})",
        )

    return True, None
