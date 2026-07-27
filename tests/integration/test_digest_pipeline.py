"""Integration test for User Story 1 acceptance scenarios (tasks.md T033,
spec.md User Story 1, quickstart.md Scenario 1).

Exercises the full orchestrator wiring (Fetch → Filter → Detect → Cluster →
Summarize → Rank → Digest/DigestTopicResult/Theme/SourcePost persistence)
against a real in-memory SQLite session. External services (TwitterAPI.io,
Claude, Resend) are monkeypatched at the names `src.pipeline.orchestrator`
imports them under — never a live network call. Filter and Detect run for
real (fully deterministic, no external dependency); Cluster runs for real in
the near-duplicate test via an injected fixed embed_fn, and is stubbed to a
single-group passthrough elsewhere since Cluster's own algorithm is already
covered by tests/unit/test_cluster.py.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from src.agent.draft_post import DraftPostResult
from src.agent.summarize import SummarizeInput, SummarizeResult
from src.config import Config
from src.models.digest import DigestRunType, DigestStatus
from src.models.digest_topic_result import DigestTopicOutcome
from src.models.source_post import FilterOutcome
from src.models.theme import Theme
from src.models.topic import Topic, TopicStatus
from src.models.topic_baseline_snapshot import TopicBaselineSnapshot
from src.models.user import User
from src.pipeline import orchestrator as orchestrator_module
from src.pipeline.cluster import ThemeCandidate
from src.pipeline.cluster import cluster_posts as real_cluster_posts
from src.pipeline.fetch import AuthorMetadata, FetchError, FetchErrorKind, FetchResult, RawPost
from src.pipeline.filter import filter_posts
from src.pipeline.orchestrator import run_digest

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def _config() -> Config:
    return Config(
        twitterapi_io_key="test-twitterapi-key",
        anthropic_api_key="test-anthropic-key",
        resend_api_key="test-resend-key",
        claude_model="claude-sonnet-5",
    )


def _clean_post(post_id: str, text: str, *, author: str | None = None, posted_at=NOW) -> RawPost:
    """A RawPost that resolves to CLEAR_KEEP at Filter Tier 1 — established
    account, no links/spam, low velocity — so no embedding call is ever
    needed to determine its filter_outcome."""
    return RawPost(
        x_post_id=post_id,
        author_handle=author or f"real_user_{post_id}",
        text=text,
        posted_at=posted_at,
        author_metadata=AuthorMetadata(
            account_age_days=500, followers_count=5000, following_count=500, post_frequency=2.0
        ),
    )


def _seed_user(session) -> User:
    user = User(email="pilot@example.com", x_account_handle="pilot")
    session.add(user)
    session.flush()
    return user


def _seed_topic(session, user: User, name: str, *, first_tracked_days_ago: int) -> Topic:
    # Derived from the real wall clock (not the fixed `NOW` constant used for
    # post timestamps below) since `Topic.observation_period_active` compares
    # against `datetime.now(UTC)` at evaluation time.
    first_tracked_at = datetime.now(UTC) - timedelta(days=first_tracked_days_ago)
    topic = Topic(
        user_id=user.id,
        name=name,
        x_handles=[],
        status=TopicStatus.ACTIVE,
        first_tracked_at=first_tracked_at,
    )
    session.add(topic)
    session.flush()
    return topic


def _seed_baseline(session, topic: Topic, *, daily_count: int, days: int = 7) -> None:
    today = date.today()
    for i in range(1, days + 1):
        session.add(
            TopicBaselineSnapshot(
                topic_id=topic.id,
                window_date=today - timedelta(days=i),
                filtered_post_count=daily_count,
            )
        )
    session.flush()


def _fake_fetch(results: dict[str, FetchResult]):
    def fake(topic_name, x_handles, *, api_key):
        return results[topic_name]

    return fake


def _orthogonal_embed_fn(texts: list[str]) -> list[list[float]]:
    """One-hot vectors, one dimension per input — every pair has cosine
    similarity 0, so Filter Tier 2's coordinated-content check never fires
    regardless of how textually similar the inputs are. Used to keep Filter's
    *real* Tier 1 + Tier 2 composite-threshold logic exercised end-to-end
    without depending on a live Ollama server (templated/near-duplicate test
    post text can otherwise land Tier 1 in 'ambiguous', which would escalate
    to a real embedding call if left at its default)."""
    n = len(texts)
    return [[1.0 if i == j else 0.0 for i in range(n)] for j in range(n)]


@pytest.fixture(autouse=True)
def _hermetic_filter(monkeypatch):
    """Route Filter's Tier 2 embedding calls through `_orthogonal_embed_fn`
    instead of real Ollama, for every test in this module — Filter's own
    Tier 1/Tier 2 logic still runs for real (contracts/pipeline-stages.md
    § Filter), only the embedding *source* is stubbed."""
    monkeypatch.setattr(
        orchestrator_module,
        "filter_posts",
        lambda posts: filter_posts(posts, embed_fn=_orthogonal_embed_fn),
    )


def _fake_summarize_by_spike():
    """A Summarize stub whose confidence tracks the (already-deterministic)
    spike_ratio signal — Summarize's own contract behavior is covered by
    tests/contract/test_claude_summarize.py, so this only needs to prove the
    orchestrator wires its output into a persisted Theme correctly."""

    def fake(data: SummarizeInput, *, api_key, model) -> SummarizeResult:
        is_strong_spike = data.spike_ratio is not None and data.spike_ratio >= 3.0
        return SummarizeResult(
            summary=f"Summary for {data.topic_name} ({data.cluster_post_count} posts)",
            rationale=f"spike_ratio={data.spike_ratio}",
            confidence_score=90 if is_strong_spike else 40,
        )

    return fake


def _single_group_cluster(posts: list[RawPost]) -> list[ThemeCandidate]:
    """Collapse every kept post into one ThemeCandidate — Cluster's own
    similarity algorithm is unit-tested separately (test_cluster.py); this
    stub isolates the orchestrator-wiring test from needing live Ollama."""
    return [ThemeCandidate(posts=tuple(posts))] if posts else []


@pytest.fixture(autouse=True)
def _stub_notification(monkeypatch):
    """Never hit a real network for the digest-completion email in these
    orchestrator-wiring tests (covered separately by test_resend.py)."""
    monkeypatch.setattr(
        orchestrator_module,
        "send_digest_completion_notification",
        lambda digest, user, *, api_key: False,
    )


@pytest.fixture(autouse=True)
def _stub_draft_post(monkeypatch):
    """Never hit a real Claude API for Draft Post generation in these
    orchestrator-wiring tests (covered separately by
    tests/contract/test_claude_summarize.py-style coverage for Draft Post,
    and tests/integration/test_posting_autonomy.py for US4's own wiring).
    Every PostingMode created here defaults to manual, so this never reaches
    an actual X publish call either."""
    monkeypatch.setattr(
        orchestrator_module,
        "generate_draft_post",
        lambda data, *, api_key, model: DraftPostResult(draft_text=f"Draft: {data.theme_summary}"),
    )


def test_spiking_topic_surfaces_a_theme_with_summary_rationale_confidence_and_examples(
    db_session, monkeypatch
):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user, "AAPL", first_tracked_days_ago=30)
    _seed_baseline(db_session, topic, daily_count=10)  # baseline mean = 10

    posts = [_clean_post(str(i), f"Distinct post number {i} about AAPL") for i in range(35)]
    monkeypatch.setattr(
        orchestrator_module,
        "fetch_topic_posts",
        _fake_fetch({"AAPL": FetchResult(posts=posts, error=None)}),
    )
    monkeypatch.setattr(orchestrator_module, "cluster_posts", _single_group_cluster)
    monkeypatch.setattr(orchestrator_module, "summarize_theme", _fake_summarize_by_spike())

    run_digest(db_session, user, [topic], run_type=DigestRunType.ON_DEMAND, config=_config())

    themes = db_session.query(Theme).all()
    assert len(themes) == 1
    theme = themes[0]
    assert theme.summary
    assert theme.rationale
    assert theme.confidence_score == 90
    assert theme.is_spike is True
    assert theme.spike_ratio == pytest.approx(3.5)  # 35 kept / 10 baseline
    assert theme.cluster_post_count == 35

    example_posts = [sp for sp in theme_source_posts(db_session, theme) if sp.is_example]
    assert 3 <= len(example_posts) <= 5


def theme_source_posts(session, theme: Theme):
    from src.models.source_post import SourcePost

    return session.query(SourcePost).filter_by(theme_id=theme.id).all()


def test_control_topic_is_not_falsely_flagged_as_a_spike(db_session, monkeypatch):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user, "CONTROL", first_tracked_days_ago=30)
    _seed_baseline(db_session, topic, daily_count=10)  # baseline mean = 10

    posts = [
        _clean_post(str(i), f"Normal chatter {i} about CONTROL") for i in range(11)
    ]  # ~baseline
    monkeypatch.setattr(
        orchestrator_module,
        "fetch_topic_posts",
        _fake_fetch({"CONTROL": FetchResult(posts=posts, error=None)}),
    )
    monkeypatch.setattr(orchestrator_module, "cluster_posts", _single_group_cluster)
    monkeypatch.setattr(orchestrator_module, "summarize_theme", _fake_summarize_by_spike())

    run_digest(db_session, user, [topic], run_type=DigestRunType.ON_DEMAND, config=_config())

    themes = db_session.query(Theme).all()
    assert len(themes) == 1
    assert themes[0].is_spike is False


def test_topic_within_observation_period_never_flags_spike_regardless_of_activity(
    db_session, monkeypatch
):
    user = _seed_user(db_session)
    # Inside the 7-day observation window — FR-005 requires is_spike=False
    # unconditionally, no matter how much raw activity there is.
    topic = _seed_topic(db_session, user, "NEWTOPIC", first_tracked_days_ago=3)

    posts = [_clean_post(str(i), f"Huge burst of activity {i} about NEWTOPIC") for i in range(200)]
    monkeypatch.setattr(
        orchestrator_module,
        "fetch_topic_posts",
        _fake_fetch({"NEWTOPIC": FetchResult(posts=posts, error=None)}),
    )
    monkeypatch.setattr(orchestrator_module, "cluster_posts", _single_group_cluster)
    monkeypatch.setattr(orchestrator_module, "summarize_theme", _fake_summarize_by_spike())

    run_digest(db_session, user, [topic], run_type=DigestRunType.ON_DEMAND, config=_config())

    themes = db_session.query(Theme).all()
    assert len(themes) == 1
    assert themes[0].is_spike is False
    assert themes[0].spike_ratio is None
    assert themes[0].cluster_post_count == 200  # raw activity still shown, just not flagged


def test_near_duplicate_posts_collapse_into_one_theme_via_real_cluster(db_session, monkeypatch):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user, "DUPTOPIC", first_tracked_days_ago=30)
    _seed_baseline(db_session, topic, daily_count=10)

    duplicate_posts = [
        _clean_post("1", "This ticker is about to explode, get in now"),
        _clean_post("2", "This ticker is about to explode, get in right now"),
        _clean_post("3", "This ticker is about to explode, get in soon"),
        _clean_post("4", "This ticker is about to explode, get in today"),
    ]
    unrelated_post = _clean_post("5", "Completely unrelated commentary about the weather today")
    posts = [*duplicate_posts, unrelated_post]
    vectors = [
        [1.0, 0.0, 0.0],
        [0.99, 0.02, 0.0],
        [0.98, 0.03, 0.0],
        [0.97, 0.04, 0.0],
        [0.0, 0.0, 1.0],
    ]

    monkeypatch.setattr(
        orchestrator_module,
        "fetch_topic_posts",
        _fake_fetch({"DUPTOPIC": FetchResult(posts=posts, error=None)}),
    )
    monkeypatch.setattr(
        orchestrator_module,
        "cluster_posts",
        lambda kept_posts: real_cluster_posts(kept_posts, embed_fn=lambda texts: vectors),
    )
    monkeypatch.setattr(orchestrator_module, "summarize_theme", _fake_summarize_by_spike())

    run_digest(db_session, user, [topic], run_type=DigestRunType.ON_DEMAND, config=_config())

    themes = db_session.query(Theme).order_by(Theme.cluster_post_count.desc()).all()
    assert len(themes) == 2
    assert themes[0].cluster_post_count == 4
    assert themes[1].cluster_post_count == 1

    duplicate_theme_posts = theme_source_posts(db_session, themes[0])
    assert {sp.x_post_id for sp in duplicate_theme_posts} == {"1", "2", "3", "4"}
    assert all(sp.is_example for sp in duplicate_theme_posts)  # fewer than 5 -> all are examples


def test_fetch_error_on_one_topic_never_halts_the_run_for_another(db_session, monkeypatch):
    user = _seed_user(db_session)
    healthy_topic = _seed_topic(db_session, user, "HEALTHY", first_tracked_days_ago=30)
    broken_topic = _seed_topic(db_session, user, "BROKEN", first_tracked_days_ago=30)
    _seed_baseline(db_session, healthy_topic, daily_count=10)

    posts = [_clean_post(str(i), f"Normal post {i} about HEALTHY") for i in range(11)]
    monkeypatch.setattr(
        orchestrator_module,
        "fetch_topic_posts",
        _fake_fetch(
            {
                "HEALTHY": FetchResult(posts=posts, error=None),
                "BROKEN": FetchResult(
                    posts=None, error=FetchError(kind=FetchErrorKind.ERROR, detail="persistent 500")
                ),
            }
        ),
    )
    monkeypatch.setattr(orchestrator_module, "cluster_posts", _single_group_cluster)
    monkeypatch.setattr(orchestrator_module, "summarize_theme", _fake_summarize_by_spike())

    digest = run_digest(
        db_session,
        user,
        [healthy_topic, broken_topic],
        run_type=DigestRunType.ON_DEMAND,
        config=_config(),
    )

    dtrs = {dtr.topic_id: dtr for dtr in _digest_topic_results(db_session, digest.id)}
    assert dtrs[healthy_topic.id].outcome == DigestTopicOutcome.THEMES_PRESENT
    assert dtrs[broken_topic.id].outcome == DigestTopicOutcome.FETCH_ERROR
    assert dtrs[broken_topic.id].error_detail == "persistent 500"
    assert digest.status == DigestStatus.PARTIAL


def test_rate_limited_fetch_marks_topic_incomplete_rate_limited_not_generic_fetch_error(
    db_session, monkeypatch
):
    """Edge case from quickstart.md: rate limits hit mid-run must preserve
    partial results and mark the affected topic `incomplete_rate_limited`
    specifically (not the generic `fetch_error`), while other topics still
    complete (FR-002, FR-017)."""
    user = _seed_user(db_session)
    healthy_topic = _seed_topic(db_session, user, "HEALTHY", first_tracked_days_ago=30)
    limited_topic = _seed_topic(db_session, user, "LIMITED", first_tracked_days_ago=30)
    _seed_baseline(db_session, healthy_topic, daily_count=10)

    posts = [_clean_post(str(i), f"Normal post {i} about HEALTHY") for i in range(11)]
    monkeypatch.setattr(
        orchestrator_module,
        "fetch_topic_posts",
        _fake_fetch(
            {
                "HEALTHY": FetchResult(posts=posts, error=None),
                "LIMITED": FetchResult(
                    posts=None,
                    error=FetchError(kind=FetchErrorKind.RATE_LIMITED, detail="429 rate limited"),
                ),
            }
        ),
    )
    monkeypatch.setattr(orchestrator_module, "cluster_posts", _single_group_cluster)
    monkeypatch.setattr(orchestrator_module, "summarize_theme", _fake_summarize_by_spike())

    digest = run_digest(
        db_session,
        user,
        [healthy_topic, limited_topic],
        run_type=DigestRunType.ON_DEMAND,
        config=_config(),
    )

    dtrs = {dtr.topic_id: dtr for dtr in _digest_topic_results(db_session, digest.id)}
    assert dtrs[healthy_topic.id].outcome == DigestTopicOutcome.THEMES_PRESENT
    assert dtrs[limited_topic.id].outcome == DigestTopicOutcome.INCOMPLETE_RATE_LIMITED
    assert dtrs[limited_topic.id].error_detail == "429 rate limited"
    # Partial results preserved: the healthy topic's Theme still exists.
    assert digest.status == DigestStatus.PARTIAL


def _digest_topic_results(session, digest_id):
    from src.models.digest_topic_result import DigestTopicResult

    return session.query(DigestTopicResult).filter_by(digest_id=digest_id).all()


def test_zero_fetched_posts_marks_no_significant_activity(db_session, monkeypatch):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user, "QUIET", first_tracked_days_ago=30)

    monkeypatch.setattr(
        orchestrator_module,
        "fetch_topic_posts",
        _fake_fetch({"QUIET": FetchResult(posts=[], error=None)}),
    )

    digest = run_digest(
        db_session, user, [topic], run_type=DigestRunType.ON_DEMAND, config=_config()
    )

    dtrs = _digest_topic_results(db_session, digest.id)
    assert len(dtrs) == 1
    assert dtrs[0].outcome == DigestTopicOutcome.NO_SIGNIFICANT_ACTIVITY
    assert db_session.query(Theme).count() == 0


def test_all_posts_filtered_as_noise_when_only_bot_spam_is_fetched(db_session, monkeypatch):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user, "SPAMMY", first_tracked_days_ago=30)

    bot_posts = [
        RawPost(
            x_post_id=f"bot-{i}",
            author_handle=f"bot_{i}",
            text="DM me for guaranteed profits on this trade",
            posted_at=NOW,
            author_metadata=AuthorMetadata(
                account_age_days=3, followers_count=5, following_count=800, post_frequency=200.0
            ),
        )
        for i in range(5)
    ]
    monkeypatch.setattr(
        orchestrator_module,
        "fetch_topic_posts",
        _fake_fetch({"SPAMMY": FetchResult(posts=bot_posts, error=None)}),
    )

    digest = run_digest(
        db_session, user, [topic], run_type=DigestRunType.ON_DEMAND, config=_config()
    )

    dtrs = _digest_topic_results(db_session, digest.id)
    assert dtrs[0].outcome == DigestTopicOutcome.ALL_FILTERED_AS_NOISE
    assert db_session.query(Theme).count() == 0


def test_labeled_bot_spam_fixture_excludes_at_least_90_percent():
    """Filter-stage check against the T032 labeled fixture (SC-002,
    quickstart.md Scenario 1 step 7) — run directly against `filter_posts`,
    not through the orchestrator, since this validates Filter's own
    precision rather than run-wiring."""
    fixture_path = FIXTURES_DIR / "labeled_bot_spam_posts.json"
    records = json.loads(fixture_path.read_text())
    assert len(records) == 50

    posts_by_id: dict[str, RawPost] = {}
    labels: dict[str, str] = {}
    for record in records:
        post = RawPost(
            x_post_id=record["x_post_id"],
            author_handle=record["author_handle"],
            text=record["text"],
            posted_at=datetime.fromisoformat(record["posted_at"]),
            author_metadata=AuthorMetadata(
                account_age_days=record["account_age_days"],
                followers_count=record["followers_count"],
                following_count=record["following_count"],
                post_frequency=record["post_frequency"],
            ),
        )
        posts_by_id[record["x_post_id"]] = post
        labels[record["x_post_id"]] = record["label"]

    # Same hermetic embed_fn as `_hermetic_filter` above — the fixture is
    # designed so every post resolves at Tier 1 alone, but this keeps the
    # test robust (rather than asserting on it) in case a genuine/bot-spam
    # pair happens to land ambiguous at Tier 1.
    filtered = filter_posts(list(posts_by_id.values()), embed_fn=_orthogonal_embed_fn)

    bot_spam_ids = {post_id for post_id, label in labels.items() if label == "bot_spam"}
    excluded_bot_spam = {
        f.post.x_post_id
        for f in filtered
        if f.post.x_post_id in bot_spam_ids and f.filter_outcome != FilterOutcome.KEPT
    }

    exclusion_rate = len(excluded_bot_spam) / len(bot_spam_ids)
    assert exclusion_rate >= 0.90
