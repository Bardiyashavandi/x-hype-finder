"""PostingMode state machine (tasks.md T058, data-model.md § PostingMode,
FR-010, FR-011, FR-013, FR-022).

Encodes every transition/gate as explicit, testable logic rather than
incidental checks scattered across callers (plan.md Constitution Principle
III): the manual→autonomous switch (validation-period + live bio-label
gates), the always-allowed autonomous→manual fallback, the kill switch
(which forces manual-hold *behavior* immediately, independent of `mode`
itself — FR-022), and `route_new_draft`, the pure threshold-routing decision
a freshly-created `DraftPost` gets exactly once (data-model.md's state
machine), never revisited by a later mode switch (FR-010 edge case).
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime, timedelta

import tweepy
from sqlalchemy.orm import Session

from src.db.scoped import scoped_select
from src.models.posting_mode import PostingMode, PostingModeValue
from src.models.user import User
from src.posting.bio_check import check_bio_has_automated_label

# data-model.md: "validation_period_ends_at: 3 weeks from first run" — anchored
# from a user's first-ever digest run (see get_or_create_posting_mode).
VALIDATION_PERIOD = timedelta(weeks=3)

# spec.md Assumptions: "the precise numeric confidence threshold ... is a
# parameter tuned during implementation rather than fixed at the
# specification level" — 70 sits in Summarize's own "strong spike, high
# diversity" calibration band (src/agent/summarize.py), a reasonable MVP
# default subject to tuning post-launch.
DEFAULT_CONFIDENCE_THRESHOLD = 70


class PostingModeError(RuntimeError):
    """Raised when a mode transition is rejected (e.g. a blocked autonomous switch)."""


class DraftRouting(enum.StrEnum):
    """Where a freshly-created DraftPost should land, decided once at
    creation time from the PostingMode in effect at that instant."""

    HOLD_MANUAL = "hold_manual"
    HOLD_BELOW_THRESHOLD = "hold_below_threshold"
    ELIGIBLE_FOR_AUTONOMOUS_PUBLISH = "eligible_for_autonomous_publish"


def get_or_create_posting_mode(
    session: Session, user: User, *, now: datetime | None = None
) -> PostingMode:
    """Fetch this user's `PostingMode` row, creating it (manual, default
    threshold, `validation_period_ends_at` = `now` + 3 weeks) on first use —
    i.e. anchored to this user's first digest run, per data-model.md."""
    existing = session.execute(scoped_select(PostingMode, user.id)).scalar_one_or_none()
    if existing is not None:
        return existing

    effective_now = now if now is not None else datetime.now(UTC)
    posting_mode = PostingMode(
        user_id=user.id,
        mode=PostingModeValue.MANUAL,
        confidence_threshold=DEFAULT_CONFIDENCE_THRESHOLD,
        validation_period_ends_at=effective_now + VALIDATION_PERIOD,
    )
    session.add(posting_mode)
    session.flush()
    return posting_mode


def _as_aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def effective_mode(posting_mode: PostingMode) -> PostingModeValue:
    """The mode that actually governs behavior right now — the kill switch
    forces MANUAL regardless of the stored `mode` field (FR-022), so every
    caller must go through this rather than reading `posting_mode.mode`
    directly."""
    if posting_mode.kill_switch_engaged:
        return PostingModeValue.MANUAL
    return posting_mode.mode


def is_autonomous_switch_allowed(
    posting_mode: PostingMode, *, bio_has_automated_label: bool, now: datetime | None = None
) -> tuple[bool, str | None]:
    """Pure gate check (data-model.md § PostingMode Validation, FR-011,
    FR-013) — returns `(allowed, rejection_reason)`."""
    effective_now = now if now is not None else datetime.now(UTC)
    validation_period_ends_at = _as_aware(posting_mode.validation_period_ends_at)

    if effective_now < validation_period_ends_at:
        return (
            False,
            "still within the 3-week validation period "
            f"(ends {validation_period_ends_at.isoformat()})",
        )
    if not bio_has_automated_label:
        return False, 'X account bio does not carry a visible "automated" label'
    return True, None


def switch_to_autonomous(
    posting_mode: PostingMode, *, x_client: tweepy.Client, now: datetime | None = None
) -> None:
    """Attempt the manual→autonomous switch (FR-011). Live-checks the bio
    label at this exact instant (FR-013) — raises `PostingModeError` with no
    state change if either gate fails. On success, applies from the next
    draft-routing decision onward only; already-created DraftPost rows are
    never revisited (data-model.md)."""
    effective_now = now if now is not None else datetime.now(UTC)
    bio_ok = check_bio_has_automated_label(x_client)
    allowed, reason = is_autonomous_switch_allowed(
        posting_mode, bio_has_automated_label=bio_ok, now=effective_now
    )
    if not allowed:
        raise PostingModeError(f"Cannot switch to autonomous mode: {reason}")

    posting_mode.mode = PostingModeValue.AUTONOMOUS
    posting_mode.updated_at = effective_now


def switch_to_manual(posting_mode: PostingMode, *, now: datetime | None = None) -> None:
    """Always allowed — the fail-safe direction (contracts/cli-commands.md §
    `posting mode set manual`)."""
    posting_mode.mode = PostingModeValue.MANUAL
    posting_mode.updated_at = now if now is not None else datetime.now(UTC)


def set_kill_switch(
    posting_mode: PostingMode, *, engaged: bool, now: datetime | None = None
) -> None:
    """FR-022: when engaged, forces manual-hold behavior immediately via
    `effective_mode`, regardless of `mode` or any already-computed
    confidence scores."""
    posting_mode.kill_switch_engaged = engaged
    posting_mode.updated_at = now if now is not None else datetime.now(UTC)


def route_new_draft(
    posting_mode: PostingMode, confidence_score: int, *, now: datetime | None = None
) -> DraftRouting:
    """The threshold-routing decision made exactly once at DraftPost creation
    time (data-model.md's state machine, FR-010, FR-012). Does not itself
    check the rolling 24h/5-post cap or jitter gate — those additionally
    gate `ELIGIBLE_FOR_AUTONOMOUS_PUBLISH` before an actual publish attempt
    (src/posting/rate_limit.py, src/posting/publish.py)."""
    if effective_mode(posting_mode) == PostingModeValue.MANUAL:
        return DraftRouting.HOLD_MANUAL
    if confidence_score < posting_mode.confidence_threshold:
        return DraftRouting.HOLD_BELOW_THRESHOLD
    return DraftRouting.ELIGIBLE_FOR_AUTONOMOUS_PUBLISH
