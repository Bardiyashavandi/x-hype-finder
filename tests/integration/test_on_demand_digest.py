"""Integration test for User Story 2 acceptance scenarios (tasks.md T048,
spec.md User Story 2, quickstart.md Scenario 2).

Covers two things: the orchestrator-level `<5 minute` on-demand budget
instrumentation (T050 — `Digest.started_at`/`completed_at` and the logged
duration) and format/quality parity between an `on_demand` and a `scheduled`
run of the same orchestrator entry point, plus the CLI's `--topic` scoping
(T049) that lets `digest run` target a single topic instead of every active
one.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.agent.draft_post import DraftPostResult
from src.agent.summarize import SummarizeInput, SummarizeResult
from src.cli import digest as digest_cli
from src.config import Config
from src.models.digest import Digest, DigestRunType
from src.models.digest_topic_result import DigestTopicResult
from src.models.theme import Theme
from src.models.topic import Topic, TopicStatus
from src.models.user import User
from src.pipeline import orchestrator as orchestrator_module
from src.pipeline.cluster import ThemeCandidate
from src.pipeline.fetch import AuthorMetadata, FetchResult, RawPost
from src.pipeline.filter import filter_posts
from src.pipeline.orchestrator import ON_DEMAND_SINGLE_TOPIC_BUDGET_SECONDS, run_digest

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def _config() -> Config:
    return Config(
        twitterapi_io_key="test-twitterapi-key",
        anthropic_api_key="test-anthropic-key",
        resend_api_key="test-resend-key",
        claude_model="claude-sonnet-5",
    )


def _clean_post(post_id: str, text: str, *, author: str | None = None) -> RawPost:
    return RawPost(
        x_post_id=post_id,
        author_handle=author or f"real_user_{post_id}",
        text=text,
        posted_at=NOW,
        author_metadata=AuthorMetadata(
            account_age_days=500, followers_count=5000, following_count=500, post_frequency=2.0
        ),
    )


def _seed_user(session, *, email: str = "pilot@example.com") -> User:
    user = User(email=email, x_account_handle="pilot")
    session.add(user)
    session.flush()
    return user


def _seed_topic(session, user: User, name: str, *, first_tracked_days_ago: int = 30) -> Topic:
    topic = Topic(
        user_id=user.id,
        name=name,
        x_handles=[],
        status=TopicStatus.ACTIVE,
        first_tracked_at=datetime.now(UTC) - timedelta(days=first_tracked_days_ago),
    )
    session.add(topic)
    session.flush()
    return topic


def _orthogonal_embed_fn(texts: list[str]) -> list[list[float]]:
    n = len(texts)
    return [[1.0 if i == j else 0.0 for i in range(n)] for j in range(n)]


def _single_group_cluster(posts: list[RawPost]) -> list[ThemeCandidate]:
    return [ThemeCandidate(posts=tuple(posts))] if posts else []


def _fake_summarize() -> Callable[..., SummarizeResult]:
    def fake(data: SummarizeInput, *, api_key, model) -> SummarizeResult:
        return SummarizeResult(
            summary=f"Summary for {data.topic_name} ({data.cluster_post_count} posts)",
            rationale=f"spike_ratio={data.spike_ratio}",
            confidence_score=75,
        )

    return fake


@pytest.fixture(autouse=True)
def _hermetic_pipeline(monkeypatch):
    """Same hermetic stubs as test_digest_pipeline.py — no live Ollama/Claude/
    Resend calls, Filter's own Tier 1/Tier 2 logic still runs for real."""
    monkeypatch.setattr(
        orchestrator_module,
        "filter_posts",
        lambda posts: filter_posts(posts, embed_fn=_orthogonal_embed_fn),
    )
    monkeypatch.setattr(orchestrator_module, "cluster_posts", _single_group_cluster)
    monkeypatch.setattr(orchestrator_module, "summarize_theme", _fake_summarize())
    monkeypatch.setattr(
        orchestrator_module,
        "send_digest_completion_notification",
        lambda digest, user, *, api_key: False,
    )
    monkeypatch.setattr(
        orchestrator_module,
        "generate_draft_post",
        lambda data, *, api_key, model: DraftPostResult(draft_text=f"Draft: {data.theme_summary}"),
    )


def _fetch_stub(topic_name: str, posts: list[RawPost]):
    def fake(name, x_handles, *, api_key):
        assert name == topic_name
        return FetchResult(posts=posts, error=None)

    return fake


def test_on_demand_single_topic_run_completes_well_within_the_five_minute_budget(
    db_session, monkeypatch
):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user, "AAPL")
    posts = [_clean_post(str(i), f"Distinct post number {i} about AAPL") for i in range(11)]
    monkeypatch.setattr(orchestrator_module, "fetch_topic_posts", _fetch_stub("AAPL", posts))

    started = time.perf_counter()
    digest = run_digest(
        db_session, user, [topic], run_type=DigestRunType.ON_DEMAND, config=_config()
    )
    elapsed = time.perf_counter() - started

    assert elapsed < ON_DEMAND_SINGLE_TOPIC_BUDGET_SECONDS
    assert (digest.completed_at - digest.started_at).total_seconds() >= 0


def test_on_demand_run_duration_is_logged_without_a_budget_warning(db_session, monkeypatch, caplog):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user, "AAPL")
    posts = [_clean_post(str(i), f"Distinct post number {i} about AAPL") for i in range(11)]
    monkeypatch.setattr(orchestrator_module, "fetch_topic_posts", _fetch_stub("AAPL", posts))

    with caplog.at_level(logging.INFO, logger="src.pipeline.orchestrator"):
        run_digest(db_session, user, [topic], run_type=DigestRunType.ON_DEMAND, config=_config())

    assert "digest run completed in" in caplog.text
    assert "exceeded the" not in caplog.text


def test_on_demand_run_over_budget_logs_a_warning(db_session, monkeypatch, caplog):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user, "AAPL")
    posts = [_clean_post(str(i), f"Distinct post number {i} about AAPL") for i in range(11)]
    monkeypatch.setattr(orchestrator_module, "fetch_topic_posts", _fetch_stub("AAPL", posts))

    real_datetime = orchestrator_module.datetime
    calls = {"n": 0}

    class _SlowDatetime:
        @staticmethod
        def now(tz=None):
            calls["n"] += 1
            # First call is Digest.started_at, second is Digest.completed_at —
            # simulate a run that overran the 5-minute budget.
            if calls["n"] == 1:
                return real_datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
            return real_datetime(2026, 7, 22, 12, 6, tzinfo=UTC)

    monkeypatch.setattr(orchestrator_module, "datetime", _SlowDatetime)

    with caplog.at_level(logging.WARNING, logger="src.pipeline.orchestrator"):
        run_digest(db_session, user, [topic], run_type=DigestRunType.ON_DEMAND, config=_config())

    assert "exceeded the" in caplog.text


def test_on_demand_and_scheduled_runs_produce_matching_theme_output(db_session, monkeypatch):
    """Same input, same orchestrator entry point, different `run_type` only —
    output format/quality (Theme fields, DigestTopicResult outcome) must
    match (User Story 2, Acceptance Scenario 2)."""
    user = _seed_user(db_session)
    on_demand_topic = _seed_topic(db_session, user, "ONDEMAND")
    scheduled_topic = _seed_topic(db_session, user, "SCHEDULED")

    same_posts_kwargs = [(str(i), f"Distinct post number {i} about a ticker") for i in range(11)]

    def fetch_stub(name, x_handles, *, api_key):
        posts = [
            _clean_post(pid, text, author=f"user_{name}_{pid}") for pid, text in same_posts_kwargs
        ]
        return FetchResult(posts=posts, error=None)

    monkeypatch.setattr(orchestrator_module, "fetch_topic_posts", fetch_stub)

    on_demand_digest = run_digest(
        db_session, user, [on_demand_topic], run_type=DigestRunType.ON_DEMAND, config=_config()
    )
    scheduled_digest = run_digest(
        db_session, user, [scheduled_topic], run_type=DigestRunType.SCHEDULED, config=_config()
    )

    on_demand_theme = db_session.execute(
        select(Theme)
        .join(DigestTopicResult, Theme.digest_topic_result_id == DigestTopicResult.id)
        .where(DigestTopicResult.digest_id == on_demand_digest.id)
    ).scalar_one()
    scheduled_theme = db_session.execute(
        select(Theme)
        .join(DigestTopicResult, Theme.digest_topic_result_id == DigestTopicResult.id)
        .where(DigestTopicResult.digest_id == scheduled_digest.id)
    ).scalar_one()

    # Summaries legitimately differ (they embed each run's own topic name) —
    # same *format* is what matters here, so compare the topic-name-free
    # suffix rather than the whole string.
    assert on_demand_theme.summary.endswith("(11 posts)")
    assert scheduled_theme.summary.endswith("(11 posts)")
    assert on_demand_theme.rationale == scheduled_theme.rationale
    assert on_demand_theme.confidence_score == scheduled_theme.confidence_score
    assert on_demand_theme.is_spike == scheduled_theme.is_spike
    assert on_demand_theme.cluster_post_count == scheduled_theme.cluster_post_count
    assert on_demand_digest.status == scheduled_digest.status
    assert on_demand_digest.run_type == DigestRunType.ON_DEMAND
    assert scheduled_digest.run_type == DigestRunType.SCHEDULED


def _run_cli(db_session, argv: list[str], monkeypatch, config: Config | None = None) -> int:
    """Run the `digest` CLI's `main()` against the test's own in-memory
    session (not a second one on the shared engine) so setup/assertions in
    the same test see the CLI's writes without extra commits — `get_session`
    is only ever used as `with get_session() as session:` in src/cli/digest.py,
    so a context manager that yields `db_session` and never closes it is a
    drop-in stand-in."""

    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(digest_cli, "get_session", fake_get_session)
    monkeypatch.setattr(digest_cli, "load_config", lambda: config or _config())
    return digest_cli.main(argv)


def test_cli_digest_run_with_topic_flag_scopes_to_a_single_topic(db_session, monkeypatch, capsys):
    user = _seed_user(db_session)
    target_topic = _seed_topic(db_session, user, "AAPL")
    other_topic = _seed_topic(db_session, user, "MSFT")

    def fetch_stub(name, x_handles, *, api_key):
        assert name == "AAPL"  # must never be called for the untargeted topic
        posts = [_clean_post(str(i), f"Distinct post number {i} about AAPL") for i in range(11)]
        return FetchResult(posts=posts, error=None)

    monkeypatch.setattr(orchestrator_module, "fetch_topic_posts", fetch_stub)

    exit_code = _run_cli(db_session, ["run", "--topic", "AAPL"], monkeypatch)
    assert exit_code == 0

    dtrs = db_session.execute(select(DigestTopicResult)).scalars().all()
    assert len(dtrs) == 1
    assert dtrs[0].topic_id == target_topic.id
    assert dtrs[0].topic_id != other_topic.id

    out = capsys.readouterr().out
    assert "completed with status" in out


def test_cli_digest_run_with_unknown_topic_name_is_rejected(db_session, monkeypatch, capsys):
    user = _seed_user(db_session)
    _seed_topic(db_session, user, "AAPL")

    exit_code = _run_cli(db_session, ["run", "--topic", "NOPE"], monkeypatch)
    assert exit_code == 1

    err = capsys.readouterr().err
    assert "NOPE" in err

    assert db_session.execute(select(Digest)).scalars().all() == []
