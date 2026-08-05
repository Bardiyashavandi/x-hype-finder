"""Integration test for User Story 3 acceptance scenarios (tasks.md T051,
spec.md User Story 3, quickstart.md Scenario 3).

Drives the `digest show <digest-id> [--topic <name>] [--full]` CLI command
end-to-end against a real in-memory SQLite session (same hermetic-external-
services pattern as tests/integration/test_digest_pipeline.py and
test_on_demand_digest.py): `--full` must surface every underlying
`SourcePost` — both clustered-into-a-Theme and Filter-excluded — with its
`filter_outcome` trail (FR-016), and a topic with nothing to show must be
rendered as an explicit state, never an empty/missing entry (FR-017).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from src.agent.draft_post import DraftPostResult
from src.agent.summarize import SummarizeInput, SummarizeResult
from src.cli import digest as digest_cli
from src.config import Config
from src.models.digest import Digest, DigestRunType, DigestStatus
from src.models.digest_topic_result import DigestTopicOutcome, DigestTopicResult
from src.models.theme import Theme
from src.models.topic import Topic, TopicStatus
from src.models.user import User
from src.pipeline import orchestrator as orchestrator_module
from src.pipeline.cluster import ThemeCandidate
from src.pipeline.fetch import AuthorMetadata, FetchResult, RawPost
from src.pipeline.filter import filter_posts

NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def _config() -> Config:
    return Config(
        twitterapi_io_key="test-twitterapi-key",
        anthropic_api_key="test-anthropic-key",
        resend_api_key="test-resend-key",
        claude_model="claude-sonnet-5",
    )


def _clean_post(post_id: str, text: str, *, author: str | None = None) -> RawPost:
    """Resolves CLEAR_KEEP at Filter Tier 1 (established account, low
    velocity, no links/spam) — deterministic without any embedding call."""
    return RawPost(
        x_post_id=post_id,
        author_handle=author or f"real_user_{post_id}",
        text=text,
        posted_at=NOW,
        author_metadata=AuthorMetadata(
            account_age_days=500, followers_count=5000, following_count=500, post_frequency=2.0
        ),
    )


def _bot_post(post_id: str) -> RawPost:
    """Resolves CLEAR_EXCLUDE at Filter Tier 1 — new/low-follower/high-
    velocity account posting a known spam pattern."""
    return RawPost(
        x_post_id=post_id,
        author_handle=f"bot_{post_id}",
        text="DM me for guaranteed profits on this trade",
        posted_at=NOW,
        author_metadata=AuthorMetadata(
            account_age_days=3, followers_count=5, following_count=800, post_frequency=200.0
        ),
    )


def _seed_user(session) -> User:
    user = User(email="pilot@example.com", x_account_handle="pilot")
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


def _seed_digest_with_themes(session, user: User, topic: Topic, confidences: list[int]) -> Digest:
    """Directly build a completed Digest / DigestTopicResult(themes_present) /
    one Theme per entry in `confidences` (rank in list order), bypassing the
    pipeline entirely. The CONFIDENCE_DISPLAY_THRESHOLD filter (src/cli/
    digest.py) is a pure display-layer read of `Theme.confidence_score`, so
    it doesn't need a real run to exercise — just Theme rows with specific
    scores."""
    digest = Digest(
        user_id=user.id,
        run_type=DigestRunType.ON_DEMAND,
        started_at=NOW,
        completed_at=NOW,
        status=DigestStatus.COMPLETED,
    )
    session.add(digest)
    session.flush()

    dtr = DigestTopicResult(
        digest_id=digest.id, topic_id=topic.id, outcome=DigestTopicOutcome.THEMES_PRESENT
    )
    session.add(dtr)
    session.flush()

    for rank, confidence in enumerate(confidences, start=1):
        session.add(
            Theme(
                digest_topic_result_id=dtr.id,
                summary=f"Summary at confidence {confidence}",
                rationale=f"Rationale at confidence {confidence}",
                confidence_score=confidence,
                is_spike=confidence >= 30,
                spike_ratio=None,
                cluster_post_count=5,
                rank=rank,
            )
        )
    session.flush()
    return digest


def _orthogonal_embed_fn(texts: list[str]) -> list[list[float]]:
    n = len(texts)
    return [[1.0 if i == j else 0.0 for i in range(n)] for j in range(n)]


def _single_group_cluster(posts: list[RawPost]) -> list[ThemeCandidate]:
    return [ThemeCandidate(posts=tuple(posts))] if posts else []


def _fake_summarize(data: SummarizeInput, *, api_key, model) -> SummarizeResult:
    return SummarizeResult(
        summary=f"Summary for {data.topic_name} ({data.cluster_post_count} posts)",
        rationale=f"spike_ratio={data.spike_ratio}",
        confidence_score=75,
    )


@pytest.fixture(autouse=True)
def _hermetic_pipeline(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "filter_posts",
        lambda posts: filter_posts(posts, embed_fn=_orthogonal_embed_fn),
    )
    monkeypatch.setattr(orchestrator_module, "cluster_posts", _single_group_cluster)
    monkeypatch.setattr(orchestrator_module, "summarize_theme", _fake_summarize)
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


def _fetch_stub(results: dict[str, list[RawPost]]):
    def fake(name, x_handles, **kwargs):
        return FetchResult(posts=results[name], error=None)

    return fake


def _run_cli(db_session, argv: list[str], monkeypatch) -> int:
    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(digest_cli, "get_session", fake_get_session)
    monkeypatch.setattr(digest_cli, "load_config", lambda: _config())
    return digest_cli.main(argv)


def test_full_flag_shows_every_underlying_post_with_its_filter_outcome(
    db_session, monkeypatch, capsys
):
    user = _seed_user(db_session)
    _seed_topic(db_session, user, "AAPL")

    kept_posts = [
        _clean_post(f"kept-{i}", f"Distinct post number {i} about AAPL") for i in range(8)
    ]
    bot_posts = [_bot_post(f"bot-{i}") for i in range(2)]
    monkeypatch.setattr(
        orchestrator_module,
        "get_fetch_provider",
        lambda **_: _fetch_stub({"AAPL": kept_posts + bot_posts}),
    )

    exit_code = _run_cli(db_session, ["run", "--topic", "AAPL"], monkeypatch)
    assert exit_code == 0
    capsys.readouterr()  # discard `run`'s stdout

    digest_id = db_session.execute(select(Digest)).scalars().one().id

    # Default view: only the curated 3-5 examples, not all 8.
    exit_code = _run_cli(db_session, ["show", str(digest_id), "--topic", "AAPL"], monkeypatch)
    assert exit_code == 0
    default_out = capsys.readouterr().out
    assert "examples (5 of 8):" in default_out
    assert "kept-6" not in default_out  # beyond the first 5 examples

    # --full: every one of the 8 clustered posts, plus the 2 Filter excluded.
    exit_code = _run_cli(
        db_session, ["show", str(digest_id), "--topic", "AAPL", "--full"], monkeypatch
    )
    assert exit_code == 0
    full_out = capsys.readouterr().out

    for i in range(8):
        assert f"kept-{i}" in full_out
        assert f"[kept] @real_user_kept-{i}" in full_out
    for i in range(2):
        assert f"bot-{i}" in full_out
    assert "excluded/unclustered posts (2):" in full_out
    assert "[excluded_rule]" in full_out


def test_all_filtered_as_noise_topic_is_rendered_explicitly(db_session, monkeypatch, capsys):
    user = _seed_user(db_session)
    _seed_topic(db_session, user, "SPAMMY")
    bot_posts = [_bot_post(f"bot-{i}") for i in range(5)]
    monkeypatch.setattr(
        orchestrator_module, "get_fetch_provider", lambda **_: _fetch_stub({"SPAMMY": bot_posts})
    )

    exit_code = _run_cli(db_session, ["run", "--topic", "SPAMMY"], monkeypatch)
    assert exit_code == 0
    capsys.readouterr()

    digest_id = db_session.execute(select(Digest)).scalars().one().id

    exit_code = _run_cli(db_session, ["show", str(digest_id)], monkeypatch)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "outcome=all_filtered_as_noise" in out
    assert "No themes" not in out  # never an empty/missing entry, an explicit state instead

    # --full still surfaces the filtered posts and their trail even though no
    # Theme was ever created for this topic.
    exit_code = _run_cli(db_session, ["show", str(digest_id), "--full"], monkeypatch)
    assert exit_code == 0
    full_out = capsys.readouterr().out
    assert "[excluded_rule]" in full_out
    for i in range(5):
        assert f"bot-{i}" in full_out


def test_no_significant_activity_topic_is_rendered_explicitly(db_session, monkeypatch, capsys):
    user = _seed_user(db_session)
    _seed_topic(db_session, user, "QUIET")
    monkeypatch.setattr(
        orchestrator_module, "get_fetch_provider", lambda **_: _fetch_stub({"QUIET": []})
    )

    exit_code = _run_cli(db_session, ["run", "--topic", "QUIET"], monkeypatch)
    assert exit_code == 0
    capsys.readouterr()

    digest_id = db_session.execute(select(Digest)).scalars().one().id

    exit_code = _run_cli(db_session, ["show", str(digest_id), "--full"], monkeypatch)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "outcome=no_significant_activity" in out


def test_topic_flag_scopes_output_to_a_single_topic(db_session, monkeypatch, capsys):
    user = _seed_user(db_session)
    _seed_topic(db_session, user, "AAPL")
    _seed_topic(db_session, user, "MSFT")

    aapl_posts = [_clean_post(f"a{i}", f"Distinct post number {i} about AAPL") for i in range(4)]
    msft_posts = [_clean_post(f"m{i}", f"Distinct post number {i} about MSFT") for i in range(4)]
    monkeypatch.setattr(
        orchestrator_module,
        "get_fetch_provider",
        lambda **_: _fetch_stub({"AAPL": aapl_posts, "MSFT": msft_posts}),
    )

    exit_code = _run_cli(db_session, ["run"], monkeypatch)
    assert exit_code == 0
    capsys.readouterr()

    digest_id = db_session.execute(select(Digest)).scalars().one().id

    exit_code = _run_cli(db_session, ["show", str(digest_id), "--topic", "AAPL"], monkeypatch)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "== AAPL ==" in out
    assert "== MSFT ==" not in out


def test_show_with_unknown_topic_name_is_rejected(db_session, monkeypatch, capsys):
    user = _seed_user(db_session)
    _seed_topic(db_session, user, "AAPL")
    posts = [_clean_post(str(i), f"Distinct post number {i} about AAPL") for i in range(4)]
    monkeypatch.setattr(
        orchestrator_module, "get_fetch_provider", lambda **_: _fetch_stub({"AAPL": posts})
    )

    exit_code = _run_cli(db_session, ["run", "--topic", "AAPL"], monkeypatch)
    assert exit_code == 0
    capsys.readouterr()

    digest_id = db_session.execute(select(Digest)).scalars().one().id

    exit_code = _run_cli(db_session, ["show", str(digest_id), "--topic", "NOPE"], monkeypatch)
    assert exit_code == 1
    err = capsys.readouterr().err
    assert "NOPE" in err


def test_default_view_hides_low_confidence_themes(db_session, monkeypatch, capsys):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user, "AAPL")
    # Chosen so no confidence value's digits are a prefix of another's (e.g.
    # avoid 5/50) — otherwise a substring assertion like "confidence 5" would
    # false-positive match inside "confidence 50".
    digest = _seed_digest_with_themes(db_session, user, topic, [80, 55, 13, 2, 37])

    exit_code = _run_cli(db_session, ["show", str(digest.id)], monkeypatch)
    assert exit_code == 0
    out = capsys.readouterr().out

    # confidence >= CONFIDENCE_DISPLAY_THRESHOLD (20): shown.
    assert "Summary at confidence 80" in out
    assert "Summary at confidence 55" in out
    assert "Summary at confidence 37" in out
    # confidence < 20: hidden — this is a display-only filter, so the
    # underlying Theme rows themselves are untouched (asserted separately
    # below by re-reading them straight from the DB).
    assert "Summary at confidence 13" not in out
    assert "Summary at confidence 2" not in out

    assert "2 additional low-confidence themes not shown — use --full to see everything." in out

    # Display-only filter (not a delete/mutation): every Theme row is still
    # in the DB regardless of what the default view chose to print.
    dtr = db_session.execute(
        select(DigestTopicResult).where(DigestTopicResult.digest_id == digest.id)
    ).scalar_one()
    stored_themes = (
        db_session.execute(select(Theme).where(Theme.digest_topic_result_id == dtr.id))
        .scalars()
        .all()
    )
    assert sorted(t.confidence_score for t in stored_themes) == [2, 13, 37, 55, 80]


def test_full_flag_still_shows_every_theme_regardless_of_confidence(
    db_session, monkeypatch, capsys
):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user, "AAPL")
    # Chosen so no confidence value's digits are a prefix of another's (e.g.
    # avoid 5/50) — otherwise a substring assertion like "confidence 5" would
    # false-positive match inside "confidence 50".
    digest = _seed_digest_with_themes(db_session, user, topic, [80, 55, 13, 2, 37])

    exit_code = _run_cli(db_session, ["show", str(digest.id), "--full"], monkeypatch)
    assert exit_code == 0
    out = capsys.readouterr().out

    for confidence in (80, 55, 13, 2, 37):
        assert f"Summary at confidence {confidence}" in out
    assert "additional low-confidence" not in out


def test_additional_low_confidence_summary_line_wording_and_accuracy(
    db_session, monkeypatch, capsys
):
    user = _seed_user(db_session)

    # Plural: 2 hidden.
    plural_topic = _seed_topic(db_session, user, "PLURAL")
    plural_digest = _seed_digest_with_themes(db_session, user, plural_topic, [80, 15, 5])
    exit_code = _run_cli(db_session, ["show", str(plural_digest.id)], monkeypatch)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "2 additional low-confidence themes not shown — use --full to see everything." in out

    # Singular: exactly 1 hidden — no trailing "s".
    singular_topic = _seed_topic(db_session, user, "SINGULAR")
    singular_digest = _seed_digest_with_themes(db_session, user, singular_topic, [80, 10])
    exit_code = _run_cli(db_session, ["show", str(singular_digest.id)], monkeypatch)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "1 additional low-confidence theme not shown — use --full to see everything." in out
    assert "1 additional low-confidence themes" not in out

    # None hidden: every theme clears the threshold — no summary line at all.
    none_topic = _seed_topic(db_session, user, "NONEHIDDEN")
    none_digest = _seed_digest_with_themes(db_session, user, none_topic, [80, 50])
    exit_code = _run_cli(db_session, ["show", str(none_digest.id)], monkeypatch)
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "additional low-confidence" not in out
