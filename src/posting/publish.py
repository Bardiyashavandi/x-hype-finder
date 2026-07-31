"""Autonomous publish client (tasks.md T062, FR-012, FR-019, FR-022;
depends on T058's mode routing and T061's rate/jitter gate).

`decide_and_publish` is the single entry point the orchestrator (T057) calls
for every freshly-created draft — it composes the mode routing decision
(src/posting/mode.py), the rate-cap/jitter gate (src/posting/rate_limit.py),
and the actual `tweepy` publish call into the one outcome a DraftPost's
`status` is assigned from at creation time, exactly once (data-model.md).

A draft that clears the confidence threshold but is blocked by the rate cap
or jitter gate is held exactly like a below-threshold draft
(`held_below_threshold`) — reusing that status rather than inventing a new
one, since the behavior is identical either way: held for manual review,
never silently discarded, reconsidered on a future run (edge case in
spec.md: "a draft's confidence falls below the posting threshold ... held
for manual review"). Only an actual `tweepy` publish-call failure — after
every gate has already passed — is surfaced as `publish_failed` with
`publish_error` populated (FR-019); gate-blocks are not failures.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime

import tweepy
from sqlalchemy.orm import Session

from src.models.draft_post import DraftPostStatus
from src.models.posting_mode import PostingMode
from src.posting.mode import DraftRouting, route_new_draft
from src.posting.rate_limit import RandomLike, can_publish_now


@dataclass(frozen=True)
class PublishOutcome:
    status: DraftPostStatus
    published_at: datetime | None
    publish_error: str | None


def decide_and_publish(
    session: Session,
    posting_mode: PostingMode,
    *,
    confidence_score: int,
    draft_text: str,
    x_client: tweepy.Client,
    now: datetime | None = None,
    rand: RandomLike = random,
) -> PublishOutcome:
    """Route a freshly-drafted post and, if eligible, attempt to publish it
    via the official X API right now.

    Never raises for an X API failure — that is surfaced as a
    `PublishOutcome(status=PUBLISH_FAILED, ...)` for the caller to persist,
    per FR-019.
    """
    effective_now = now if now is not None else datetime.now(UTC)
    routing = route_new_draft(posting_mode, confidence_score, now=effective_now)

    if routing == DraftRouting.HOLD_MANUAL:
        return PublishOutcome(DraftPostStatus.HELD_MANUAL, None, None)
    if routing == DraftRouting.HOLD_BELOW_THRESHOLD:
        return PublishOutcome(DraftPostStatus.HELD_BELOW_THRESHOLD, None, None)

    allowed, _reason = can_publish_now(
        session, posting_mode, posting_mode.user_id, now=effective_now, rand=rand
    )
    if not allowed:
        return PublishOutcome(DraftPostStatus.HELD_BELOW_THRESHOLD, None, None)

    try:
        x_client.create_tweet(text=draft_text)
    except Exception as exc:  # noqa: BLE001 - any X API failure must surface (FR-019)
        return PublishOutcome(DraftPostStatus.PUBLISH_FAILED, None, str(exc))

    posting_mode.last_post_published_at = effective_now
    return PublishOutcome(DraftPostStatus.PUBLISHED_AUTO, effective_now, None)
