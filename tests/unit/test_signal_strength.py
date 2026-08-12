"""Unit tests for Signal Strength (src/pipeline/signal_strength.py,
contracts/pipeline-stages.md § Signal Strength, data-model.md §
SignalStrength).
"""

from datetime import UTC, datetime, timedelta

from src.pipeline.fetch import AuthorMetadata, RawPost
from src.pipeline.signal_strength import compute_signal_strength

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _post(post_id: str, *, author: str, posted_at: datetime) -> RawPost:
    return RawPost(
        x_post_id=post_id,
        author_handle=author,
        text="text",
        posted_at=posted_at,
        author_metadata=AuthorMetadata(
            account_age_days=500, followers_count=100, following_count=50, post_frequency=1.0
        ),
    )


def test_zero_posts_returns_zero_count_and_none_timestamps():
    result = compute_signal_strength([], now=NOW)

    assert result.total_relevant_count == 0
    assert result.distinct_author_count == 0
    assert result.most_recent_post_at is None
    assert result.oldest_post_at is None
    assert result.posts_last_24h == 0
    assert result.posts_last_7d == 0


def test_total_relevant_count_and_distinct_author_count():
    posts = [
        _post("1", author="alice", posted_at=NOW - timedelta(hours=1)),
        _post("2", author="bob", posted_at=NOW - timedelta(hours=2)),
        _post("3", author="alice", posted_at=NOW - timedelta(days=3)),
    ]

    result = compute_signal_strength(posts, now=NOW)

    assert result.total_relevant_count == 3
    assert result.distinct_author_count == 2


def test_most_recent_and_oldest_post_at():
    posts = [
        _post("1", author="alice", posted_at=NOW - timedelta(hours=1)),
        _post("2", author="bob", posted_at=NOW - timedelta(days=5)),
    ]

    result = compute_signal_strength(posts, now=NOW)

    assert result.most_recent_post_at == NOW - timedelta(hours=1)
    assert result.oldest_post_at == NOW - timedelta(days=5)


def test_posts_last_24h_and_last_7d_recency_buckets():
    posts = [
        _post("1", author="a", posted_at=NOW - timedelta(hours=1)),  # in both buckets
        _post("2", author="b", posted_at=NOW - timedelta(days=3)),  # 7d only
        _post("3", author="c", posted_at=NOW - timedelta(days=10)),  # neither
    ]

    result = compute_signal_strength(posts, now=NOW)

    assert result.posts_last_24h == 1
    assert result.posts_last_7d == 2


def test_posts_last_7d_includes_posts_last_24h():
    posts = [_post("1", author="a", posted_at=NOW - timedelta(minutes=5))]

    result = compute_signal_strength(posts, now=NOW)

    assert result.posts_last_24h == 1
    assert result.posts_last_7d == 1


def test_no_is_spike_or_spike_ratio_field_exists():
    """Deliberate, documented absence (research.md §5) — this mode has no
    historical baseline to compare against, so those fields don't exist
    here at all, unlike src/pipeline/detect.py's DetectResult."""
    result = compute_signal_strength([], now=NOW)

    assert not hasattr(result, "is_spike")
    assert not hasattr(result, "spike_ratio")
