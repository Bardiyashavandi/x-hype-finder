"""Signal Strength: absolute volume/recency computation (tasks.md T012,
contracts/pipeline-stages.md § Signal Strength, data-model.md §
SignalStrength, research.md §5).

Fully deterministic (Constitution Principle I) — no LLM/agent judgment. This
mode's Detect-equivalent (`src/pipeline/detect.py`'s baseline-relative spike
comparison), but absolute instead of relative: a new problem space has no
history to compare against (spec.md §5.2), so no `is_spike`/`spike_ratio`
field exists here at all — a deliberate, documented absence (research.md §5),
not an oversight.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from src.pipeline.fetch import RawPost

_LAST_24H = timedelta(hours=24)
_LAST_7D = timedelta(days=7)


@dataclass(frozen=True)
class SignalStrength:
    total_relevant_count: int
    distinct_author_count: int
    most_recent_post_at: datetime | None
    oldest_post_at: datetime | None
    posts_last_24h: int
    posts_last_7d: int


def compute_signal_strength(posts: list[RawPost], *, now: datetime) -> SignalStrength:
    """Absolute volume/recency over posts that survived both Relevance
    Filter and Bot/Noise Filter. Returns `total_relevant_count=0` and
    `None` timestamps (rather than raising) when `posts` is empty —
    mirroring `DigestTopicOutcome.NO_SIGNIFICANT_ACTIVITY`'s "state the
    explicit no-activity outcome, never an empty/missing entry" principle.
    """
    if not posts:
        return SignalStrength(
            total_relevant_count=0,
            distinct_author_count=0,
            most_recent_post_at=None,
            oldest_post_at=None,
            posts_last_24h=0,
            posts_last_7d=0,
        )

    posted_ats = [post.posted_at for post in posts]
    return SignalStrength(
        total_relevant_count=len(posts),
        distinct_author_count=len({post.author_handle for post in posts}),
        most_recent_post_at=max(posted_ats),
        oldest_post_at=min(posted_ats),
        posts_last_24h=sum(1 for at in posted_ats if now - at <= _LAST_24H),
        posts_last_7d=sum(1 for at in posted_ats if now - at <= _LAST_7D),
    )
