"""Unit tests for Filter Tier 1 rule scoring (tasks.md T023).

Covers each individual heuristic (account age, follower ratio, velocity,
duplicate-text ratio, link ratio, spam patterns) via `score_tier1`'s
`reasons` output, plus the three decision buckets those scores resolve into.
"""

from datetime import UTC, datetime

from src.pipeline.fetch import AuthorMetadata, RawPost
from src.pipeline.filter import Tier1Decision, score_tier1

NOW = datetime(2026, 7, 22, tzinfo=UTC)


def _post(
    post_id: str,
    text: str,
    *,
    account_age_days: float = 400,
    followers: int = 5000,
    following: int = 500,
    post_frequency: float = 5.0,
) -> RawPost:
    return RawPost(
        x_post_id=post_id,
        author_handle=f"user_{post_id}",
        text=text,
        posted_at=NOW,
        author_metadata=AuthorMetadata(
            account_age_days=account_age_days,
            followers_count=followers,
            following_count=following,
            post_frequency=post_frequency,
        ),
    )


def test_clean_established_post_is_clear_keep():
    posts = [_post("1", "Genuinely interesting news about this ticker today.")]
    result = score_tier1(posts)["1"]
    assert result.decision == Tier1Decision.CLEAR_KEEP
    assert result.score <= 20
    assert result.reasons == ()


def test_new_account_signal_fires():
    posts = [_post("1", "Just my honest take on this.", account_age_days=5)]
    result = score_tier1(posts)["1"]
    assert "new_account" in result.reasons


def test_suspicious_follow_ratio_signal_fires():
    posts = [_post("1", "Following everyone to grow my account.", followers=10, following=500)]
    result = score_tier1(posts)["1"]
    assert "suspicious_follow_ratio" in result.reasons


def test_established_low_follower_but_proportionate_ratio_does_not_fire():
    # Low followers alone shouldn't trigger the signal without a lopsided ratio too.
    posts = [_post("1", "Small account, normal behavior.", followers=10, following=15)]
    result = score_tier1(posts)["1"]
    assert "suspicious_follow_ratio" not in result.reasons


def test_high_velocity_signal_fires():
    posts = [_post("1", "Another update from me.", post_frequency=200.0)]
    result = score_tier1(posts)["1"]
    assert "high_velocity" in result.reasons


def test_duplicate_text_signal_fires_across_batch():
    posts = [
        _post("1", "Buy the dip now before it's too late"),
        _post("2", "BUY THE DIP NOW BEFORE IT'S TOO LATE"),
        _post("3", "A totally unrelated, unique thought about the weather."),
    ]
    results = score_tier1(posts)
    assert "duplicate_text" in results["1"].reasons
    assert "duplicate_text" in results["2"].reasons
    assert "duplicate_text" not in results["3"].reasons


def test_link_heavy_signal_fires():
    posts = [_post("1", "http://spam.example/promo")]
    result = score_tier1(posts)["1"]
    assert "link_heavy" in result.reasons


def test_normal_text_with_one_short_link_does_not_fire_link_heavy():
    posts = [
        _post(
            "1",
            "Worth reading this writeup on the topic, lots of good detail here: http://x.co/a",
        )
    ]
    result = score_tier1(posts)["1"]
    assert "link_heavy" not in result.reasons


def test_spam_pattern_signal_fires():
    posts = [_post("1", "DM me for guaranteed profits on this trade")]
    result = score_tier1(posts)["1"]
    assert "spam_pattern" in result.reasons


def test_clear_exclude_when_many_signals_combine():
    posts = [
        _post(
            "1",
            "DM me now for guaranteed profits, click the link! http://spam.example/x",
            account_age_days=2,
            followers=5,
            following=800,
            post_frequency=300.0,
        ),
    ]
    result = score_tier1(posts)["1"]
    assert result.decision == Tier1Decision.CLEAR_EXCLUDE
    assert result.score >= 70


def test_ambiguous_when_some_but_not_enough_signals_combine():
    # new_account (20) + link_heavy (10) = 30: enough to leave clear-keep,
    # not enough to reach clear-exclude (70) — must escalate to Tier 2.
    posts = [_post("1", "http://x.example/promo", account_age_days=5)]
    result = score_tier1(posts)["1"]
    assert result.decision == Tier1Decision.AMBIGUOUS
    assert 20 < result.score < 70
