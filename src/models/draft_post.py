"""DraftPost model (tasks.md T015, data-model.md § DraftPost).

A system-generated post derived from a high-signal Theme, pending manual or
autonomous handling. See data-model.md's state machine (FR-010, FR-012,
FR-019): the *initial* status (which branch — held for manual review, held
below the confidence threshold, or an immediate autonomous publish attempt)
is assigned exactly once at creation, based on the PostingMode in effect at
that moment, and never retroactively changed by a later mode switch. A
`held_*` status can still transition later — see the three PUBLISHED_*
members below, which are NOT interchangeable despite all being "it got
posted": they record three genuinely different mechanisms, and which one
applies is never a judgment call once you know how the post actually went
out.

- `PUBLISHED_MANUAL`: the user posted through the X UI themselves, entirely
  outside this system, then ran `drafts mark-published` to record it after
  the fact (`src/cli/drafts.py`). No X API call was ever made by this
  codebase for this post. `tweet_id`/`tweet_url` are always `None` here —
  there is no way for this system to know them.
- `PUBLISHED_AUTO`: `decide_and_publish()`'s own confidence-threshold
  routing (`src/posting/publish.py`) decided to publish and made the
  `create_tweet()` call itself, unattended, with no human in the loop at
  that moment. `tweet_id`/`tweet_url` are populated from the real API
  response.
- `PUBLISHED_MANUAL_OVERRIDE`: a human explicitly directed this system to
  make the real `create_tweet()` call right now, for a draft that was
  sitting `HELD_MANUAL` or `HELD_BELOW_THRESHOLD` — bypassing the normal
  "hold for review, then the human posts it themselves" or confidence-gate
  flow. The system made the call (so `tweet_id`/`tweet_url` are populated,
  same as PUBLISHED_AUTO), but a human directed this specific call in the
  moment (so it's not PUBLISHED_AUTO's unattended routing either). Added
  after a real incident (2026-08-07) where a manual override was recorded
  as PUBLISHED_AUTO for lack of a status that actually fit — there is
  deliberately no CLI command that reaches this status; every occurrence is
  a one-off, hand-confirmed action, never a routine automated path.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


class DraftPostStatus(enum.StrEnum):
    HELD_MANUAL = "held_manual"
    PUBLISHED_MANUAL = "published_manual"
    HELD_BELOW_THRESHOLD = "held_below_threshold"
    PUBLISHED_AUTO = "published_auto"
    PUBLISH_FAILED = "publish_failed"
    PUBLISHED_MANUAL_OVERRIDE = "published_manual_override"


class DraftPost(Base):
    __tablename__ = "draft_posts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    theme_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("themes.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    draft_text: Mapped[str] = mapped_column(String, nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-100
    status: Mapped[DraftPostStatus] = mapped_column(Enum(DraftPostStatus), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    publish_error: Mapped[str | None] = mapped_column(String, nullable=True)
    # Populated only for PUBLISHED_AUTO / PUBLISHED_MANUAL_OVERRIDE — the two
    # statuses where this system itself made the create_tweet() call and has
    # the real response. Always None for PUBLISHED_MANUAL (see docstring above).
    tweet_id: Mapped[str | None] = mapped_column(String, nullable=True)
    tweet_url: Mapped[str | None] = mapped_column(String, nullable=True)
