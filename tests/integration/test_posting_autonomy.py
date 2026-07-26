"""Integration test for User Story 4 acceptance scenarios (tasks.md T055,
spec.md User Story 4, quickstart.md Scenario 4).

Exercises the full orchestrator wiring (Draft Post generation +
mode-routing + rate/jitter gating + publish attempt) against a real
in-memory SQLite session, plus the `posting mode`/`posting kill-switch` CLI
commands (src/cli/posting.py) for the mode-switch flow itself. External
services (Claude, the official X API, Resend) are monkeypatched at the names
`src.pipeline.orchestrator` imports them under — never a live network call.
Filter/Cluster/Summarize are stubbed exactly as in
tests/integration/test_digest_pipeline.py; this file's own focus is Draft
Post/PostingMode wiring, so it controls per-theme confidence directly via a
custom Summarize stub rather than depending on real spike math.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.agent.draft_post import DraftPostResult
from src.agent.summarize import SummarizeInput, SummarizeResult
from src.cli import posting as posting_cli
from src.config import Config
from src.models.draft_post import DraftPost, DraftPostStatus
from src.models.posting_mode import PostingMode, PostingModeValue
from src.models.topic import Topic, TopicStatus
from src.models.user import User
from src.pipeline import orchestrator as orchestrator_module
from src.pipeline.cluster import ThemeCandidate
from src.pipeline.fetch import AuthorMetadata, FetchResult, RawPost
from src.pipeline.filter import filter_posts
from src.pipeline.orchestrator import run_digest
from src.posting.mode import PostingModeError, get_or_create_posting_mode, switch_to_autonomous

NOW = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)
HIGH_CONFIDENCE = 95
LOW_CONFIDENCE = 40


def _config() -> Config:
    return Config(
        twitterapi_io_key="test-twitterapi-key",
        anthropic_api_key="test-anthropic-key",
        resend_api_key="test-resend-key",
        x_api_key="test",
        x_api_secret="test",
        x_access_token="test",
        x_access_token_secret="test",
        claude_model="claude-sonnet-5",
    )


def _seed_user(session) -> User:
    user = User(email="pilot@example.com", x_account_handle="pilot")
    session.add(user)
    session.flush()
    return user


def _seed_topic(session, user: User, name: str = "AAPL") -> Topic:
    topic = Topic(
        user_id=user.id,
        name=name,
        x_handles=[],
        status=TopicStatus.ACTIVE,
        first_tracked_at=datetime.now(UTC) - timedelta(days=30),
    )
    session.add(topic)
    session.flush()
    return topic


def _post(post_id: str, text: str) -> RawPost:
    return RawPost(
        x_post_id=post_id,
        author_handle=f"real_user_{post_id}",
        text=text,
        posted_at=NOW,
        author_metadata=AuthorMetadata(
            account_age_days=500, followers_count=5000, following_count=500, post_frequency=2.0
        ),
    )


def _orthogonal_embed_fn(texts: list[str]) -> list[list[float]]:
    n = len(texts)
    return [[1.0 if i == j else 0.0 for i in range(n)] for j in range(n)]


def _cluster_by_prefix(posts: list[RawPost]) -> list[ThemeCandidate]:
    """Groups posts by the "HIGH"/"LOW" marker in their text so each test
    controls exactly how many Themes of each confidence tier get created,
    independent of real spike/cluster math (covered elsewhere)."""
    groups: dict[str, list[RawPost]] = {}
    for post in posts:
        marker = post.text.split(":")[0]
        groups.setdefault(marker, []).append(post)
    return [ThemeCandidate(posts=tuple(group)) for group in groups.values()]


def _fake_summarize(data: SummarizeInput, *, api_key, model) -> SummarizeResult:
    is_high = any(text.startswith("HIGH") for text in data.post_texts)
    return SummarizeResult(
        summary=f"Summary for {data.topic_name}",
        rationale="HIGH marker" if is_high else "LOW marker",
        confidence_score=HIGH_CONFIDENCE if is_high else LOW_CONFIDENCE,
    )


def _fake_generate_draft_post(data, *, api_key, model) -> DraftPostResult:
    return DraftPostResult(draft_text=f"Draft: {data.theme_summary}")


@pytest.fixture(autouse=True)
def _hermetic_pipeline(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "filter_posts",
        lambda posts: filter_posts(posts, embed_fn=_orthogonal_embed_fn),
    )
    monkeypatch.setattr(orchestrator_module, "cluster_posts", _cluster_by_prefix)
    monkeypatch.setattr(orchestrator_module, "summarize_theme", _fake_summarize)
    monkeypatch.setattr(orchestrator_module, "generate_draft_post", _fake_generate_draft_post)
    monkeypatch.setattr(
        orchestrator_module,
        "send_digest_completion_notification",
        lambda digest, user, *, api_key: False,
    )


def _fetch_stub(posts: list[RawPost]):
    def fake(name, x_handles, *, api_key):
        return FetchResult(posts=posts, error=None)

    return fake


def _high_and_low_posts() -> list[RawPost]:
    high = [_post(f"high-{i}", f"HIGH: post {i} about AAPL") for i in range(4)]
    low = [_post(f"low-{i}", f"LOW: post {i} about AAPL") for i in range(4)]
    return high + low


def _drafts_for_user(session, user_id) -> list[DraftPost]:
    return session.execute(select(DraftPost).where(DraftPost.user_id == user_id)).scalars().all()


def _posting_mode_for_user(session, user_id) -> PostingMode:
    return session.execute(select(PostingMode).where(PostingMode.user_id == user_id)).scalar_one()


# --- Acceptance Scenario 1: manual-only hold during the first 3 weeks -----


def test_manual_period_holds_every_draft_regardless_of_confidence(db_session, monkeypatch):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user)
    monkeypatch.setattr(
        orchestrator_module, "fetch_topic_posts", _fetch_stub(_high_and_low_posts())
    )
    monkeypatch.setattr(orchestrator_module, "build_x_client", lambda config: None)

    run_digest(db_session, user, [topic], run_type=_on_demand(), config=_config())

    drafts = _drafts_for_user(db_session, user.id)
    assert len(drafts) == 2
    assert {d.confidence_score for d in drafts} == {HIGH_CONFIDENCE, LOW_CONFIDENCE}
    assert all(d.status == DraftPostStatus.HELD_MANUAL for d in drafts)
    assert all(d.published_at is None for d in drafts)

    posting_mode = _posting_mode_for_user(db_session, user.id)
    assert posting_mode.mode == PostingModeValue.MANUAL
    # Anchored to this first run + 3 weeks — SQLite round-trips as naive UTC,
    # so compare against a naive `NOW` too.
    assert posting_mode.validation_period_ends_at > NOW.replace(tzinfo=None)


# --- Acceptance Scenario 3: gated autonomous switch ------------------------


def test_autonomous_switch_rejected_before_validation_period_elapses(db_session, monkeypatch):
    user = _seed_user(db_session)
    posting_mode = get_or_create_posting_mode(db_session, user, now=NOW)
    db_session.commit()
    monkeypatch.setattr("src.posting.mode.check_bio_has_automated_label", lambda x_client: True)

    with pytest.raises(PostingModeError, match="validation period"):
        switch_to_autonomous(posting_mode, x_client=object(), now=NOW + timedelta(days=1))

    assert posting_mode.mode == PostingModeValue.MANUAL


def test_autonomous_switch_rejected_without_bio_label_even_after_validation_period(
    db_session, monkeypatch
):
    user = _seed_user(db_session)
    posting_mode = get_or_create_posting_mode(db_session, user, now=NOW - timedelta(weeks=4))
    db_session.commit()
    monkeypatch.setattr("src.posting.mode.check_bio_has_automated_label", lambda x_client: False)

    with pytest.raises(PostingModeError, match="automated"):
        switch_to_autonomous(posting_mode, x_client=object(), now=NOW)

    assert posting_mode.mode == PostingModeValue.MANUAL


def test_cli_posting_mode_set_autonomous_succeeds_once_gates_clear(db_session, monkeypatch, capsys):
    user = _seed_user(db_session)
    get_or_create_posting_mode(db_session, user, now=NOW - timedelta(weeks=4))
    db_session.commit()

    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(posting_cli, "get_session", fake_get_session)
    monkeypatch.setattr(posting_cli, "load_config", lambda: _config())
    monkeypatch.setattr(posting_cli, "build_x_client", lambda config: object())
    monkeypatch.setattr("src.posting.mode.check_bio_has_automated_label", lambda x_client: True)

    exit_code = posting_cli.main(["mode", "set", "autonomous"])
    assert exit_code == 0
    assert "autonomous" in capsys.readouterr().out

    posting_mode = _posting_mode_for_user(db_session, user.id)
    assert posting_mode.mode == PostingModeValue.AUTONOMOUS


# --- Acceptance Scenario 2: threshold routing after the switch -------------


def test_threshold_routing_publishes_at_or_above_and_holds_below(db_session, monkeypatch):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user)
    posting_mode = get_or_create_posting_mode(db_session, user, now=NOW - timedelta(weeks=4))
    posting_mode.mode = PostingModeValue.AUTONOMOUS
    db_session.commit()

    monkeypatch.setattr(
        orchestrator_module, "fetch_topic_posts", _fetch_stub(_high_and_low_posts())
    )
    x_client = _StubXClient()
    monkeypatch.setattr(orchestrator_module, "build_x_client", lambda config: x_client)

    run_digest(db_session, user, [topic], run_type=_on_demand(), config=_config())

    drafts = {d.confidence_score: d for d in _drafts_for_user(db_session, user.id)}
    assert drafts[HIGH_CONFIDENCE].status == DraftPostStatus.PUBLISHED_AUTO
    assert drafts[HIGH_CONFIDENCE].published_at is not None
    assert drafts[LOW_CONFIDENCE].status == DraftPostStatus.HELD_BELOW_THRESHOLD
    assert drafts[LOW_CONFIDENCE].published_at is None
    # Never silently discarded either way — both rows persist with a status.
    assert len(drafts) == 2


# --- Acceptance Scenario 4: jittered timing across publishes ---------------


def test_jitter_gate_prevents_two_high_confidence_drafts_publishing_simultaneously(
    db_session, monkeypatch
):
    """FR-014: spacing must vary, never a fixed cadence — enforced here by
    the jitter gate refusing a second publish attempt that lands within the
    same instant as the first (real random jitter is always > 0)."""
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user)
    posting_mode = get_or_create_posting_mode(db_session, user, now=NOW - timedelta(weeks=4))
    posting_mode.mode = PostingModeValue.AUTONOMOUS
    db_session.commit()

    two_high_confidence_posts = [_post(f"high-{i}", f"HIGH: post {i} about AAPL") for i in range(8)]
    # Split into two distinct HIGH clusters via distinct sub-markers so two
    # separate Themes (and thus two separate drafts) get created.
    monkeypatch.setattr(
        orchestrator_module,
        "cluster_posts",
        lambda posts: [
            ThemeCandidate(posts=tuple(posts[:4])),
            ThemeCandidate(posts=tuple(posts[4:])),
        ],
    )
    monkeypatch.setattr(
        orchestrator_module, "fetch_topic_posts", _fetch_stub(two_high_confidence_posts)
    )
    x_client = _StubXClient()
    monkeypatch.setattr(orchestrator_module, "build_x_client", lambda config: x_client)

    run_digest(db_session, user, [topic], run_type=_on_demand(), config=_config())

    drafts = _drafts_for_user(db_session, user.id)
    statuses = [d.status for d in drafts]
    assert statuses.count(DraftPostStatus.PUBLISHED_AUTO) == 1
    assert statuses.count(DraftPostStatus.HELD_BELOW_THRESHOLD) == 1
    assert x_client.create_tweet_calls == 1


# --- Acceptance Scenario 5: publish failure surfaced ------------------------


def test_publish_failure_after_clearing_threshold_is_surfaced_not_dropped(db_session, monkeypatch):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user)
    posting_mode = get_or_create_posting_mode(db_session, user, now=NOW - timedelta(weeks=4))
    posting_mode.mode = PostingModeValue.AUTONOMOUS
    db_session.commit()

    high_only_posts = [_post(f"high-{i}", f"HIGH: post {i} about AAPL") for i in range(4)]
    monkeypatch.setattr(orchestrator_module, "fetch_topic_posts", _fetch_stub(high_only_posts))
    x_client = _StubXClient(should_fail=True)
    monkeypatch.setattr(orchestrator_module, "build_x_client", lambda config: x_client)

    run_digest(db_session, user, [topic], run_type=_on_demand(), config=_config())

    drafts = _drafts_for_user(db_session, user.id)
    assert len(drafts) == 1
    assert drafts[0].status == DraftPostStatus.PUBLISH_FAILED
    assert drafts[0].publish_error is not None
    assert drafts[0].published_at is None


# --- Acceptance Scenario 6: mid-cycle switch is never retroactive ----------


def test_mid_cycle_switch_never_retroactively_publishes_prior_manual_drafts(
    db_session, monkeypatch
):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user)
    monkeypatch.setattr(
        orchestrator_module, "fetch_topic_posts", _fetch_stub(_high_and_low_posts())
    )
    monkeypatch.setattr(orchestrator_module, "build_x_client", lambda config: _StubXClient())

    # Run 1: manual period — both drafts held_manual.
    run_digest(db_session, user, [topic], run_type=_on_demand(), config=_config())
    first_run_draft_ids = {d.id for d in _drafts_for_user(db_session, user.id)}
    assert len(first_run_draft_ids) == 2

    # Switch to autonomous mid-cycle.
    posting_mode = _posting_mode_for_user(db_session, user.id)
    posting_mode.mode = PostingModeValue.AUTONOMOUS
    posting_mode.validation_period_ends_at = NOW - timedelta(days=1)
    db_session.commit()

    # Run 2: autonomous — new drafts get threshold-routed.
    run_digest(db_session, user, [topic], run_type=_on_demand(), config=_config())

    all_drafts = {d.id: d for d in _drafts_for_user(db_session, user.id)}
    assert len(all_drafts) == 4  # 2 from run 1 + 2 from run 2

    # The run-1 drafts must be untouched — never retroactively flipped to an
    # autonomous-phase status (edge case in spec.md).
    for draft_id in first_run_draft_ids:
        assert all_drafts[draft_id].status == DraftPostStatus.HELD_MANUAL


# --- Acceptance Scenario 8: kill switch halts autonomous publishing --------


def test_kill_switch_forces_manual_hold_even_in_autonomous_mode(db_session, monkeypatch):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user)
    posting_mode = get_or_create_posting_mode(db_session, user, now=NOW - timedelta(weeks=4))
    posting_mode.mode = PostingModeValue.AUTONOMOUS
    posting_mode.kill_switch_engaged = True
    db_session.commit()

    high_only_posts = [_post(f"high-{i}", f"HIGH: post {i} about AAPL") for i in range(4)]
    monkeypatch.setattr(orchestrator_module, "fetch_topic_posts", _fetch_stub(high_only_posts))
    x_client = _StubXClient()
    monkeypatch.setattr(orchestrator_module, "build_x_client", lambda config: x_client)

    run_digest(db_session, user, [topic], run_type=_on_demand(), config=_config())

    drafts = _drafts_for_user(db_session, user.id)
    assert len(drafts) == 1
    assert drafts[0].status == DraftPostStatus.HELD_MANUAL
    assert x_client.create_tweet_calls == 0


class _StubXClient:
    """A minimal `tweepy.Client`-shaped stub used across this file, tracking
    call count instead of a MagicMock so `_hermetic_pipeline`-style
    monkeypatching stays readable."""

    def __init__(self, *, should_fail: bool = False):
        self.should_fail = should_fail
        self.create_tweet_calls = 0

    def create_tweet(self, *, text: str):
        self.create_tweet_calls += 1
        if self.should_fail:
            raise RuntimeError("X API rejected the post")


def _on_demand():
    from src.models.digest import DigestRunType

    return DigestRunType.ON_DEMAND
