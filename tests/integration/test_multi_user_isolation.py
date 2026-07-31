"""Integration test for User Story 5 acceptance scenarios (tasks.md T065,
spec.md User Story 5, quickstart.md Scenario 5).

Configures two users who both track a topic with the *same name* (the
Independent Test's explicit condition — overlapping topic names must not
cause any cross-user bleed) and runs the full digest pipeline for each, then
proves zero cross-user leakage across every angle FR-015 covers:

- data: Topic, Digest, DigestTopicResult, Theme, SourcePost,
  TopicBaselineSnapshot, DraftPost, PostingMode — via `scoped_select`
  (src/db/scoped.py, T018) and the CLI commands built on it.
- credentials: `load_x_credentials_for_user` (src/config.py, T067) — one
  user's env can never resolve to another user's X OAuth credentials.
- process identity: the CLI must never guess which user it's running as when
  more than one exists (src/cli/_common.py, T066).

Same hermetic-stub approach as tests/integration/test_digest_pipeline.py and
tests/integration/test_posting_autonomy.py — a real in-memory SQLite session,
external services (Claude, Resend, the official X API) monkeypatched at the
names `src.pipeline.orchestrator` imports them under.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from src.agent.draft_post import DraftPostResult
from src.agent.summarize import SummarizeInput, SummarizeResult
from src.cli import digest as digest_cli
from src.cli import drafts as drafts_cli
from src.cli import posting as posting_cli
from src.cli import topic as topic_cli
from src.cli._common import NoCurrentUserError, resolve_current_user
from src.config import Config, ConfigError, load_x_credentials_for_user
from src.db.scoped import scoped_select
from src.models.digest import Digest, DigestRunType
from src.models.digest_topic_result import DigestTopicResult
from src.models.draft_post import DraftPost
from src.models.posting_mode import PostingMode
from src.models.source_post import SourcePost
from src.models.theme import Theme
from src.models.topic import Topic, TopicStatus
from src.models.topic_baseline_snapshot import TopicBaselineSnapshot
from src.models.user import User
from src.pipeline import orchestrator as orchestrator_module
from src.pipeline.cluster import ThemeCandidate
from src.pipeline.fetch import AuthorMetadata, FetchResult, RawPost
from src.pipeline.filter import filter_posts
from src.pipeline.orchestrator import run_digest

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)

# Both users track a topic with this exact name — the Independent Test's
# explicit "overlapping topic names" condition (spec.md User Story 5).
SHARED_TOPIC_NAME = "$TICKER"


def _config() -> Config:
    return Config(
        twitterapi_io_key="test-twitterapi-key",
        anthropic_api_key="test-anthropic-key",
        resend_api_key="test-resend-key",
        claude_model="claude-sonnet-5",
    )


def _seed_user(session, *, email: str, handle: str) -> User:
    user = User(email=email, x_account_handle=handle)
    session.add(user)
    session.flush()
    return user


def _seed_topic(session, user: User, name: str = SHARED_TOPIC_NAME) -> Topic:
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


def _single_group_cluster(posts: list[RawPost]) -> list[ThemeCandidate]:
    return [ThemeCandidate(posts=tuple(posts))] if posts else []


def _fake_summarize(data: SummarizeInput, *, api_key, model) -> SummarizeResult:
    return SummarizeResult(
        summary=f"Summary for {data.topic_name}",
        rationale=f"spike_ratio={data.spike_ratio}",
        confidence_score=90,
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
    monkeypatch.setattr(orchestrator_module, "cluster_posts", _single_group_cluster)
    monkeypatch.setattr(orchestrator_module, "summarize_theme", _fake_summarize)
    monkeypatch.setattr(orchestrator_module, "generate_draft_post", _fake_generate_draft_post)
    monkeypatch.setattr(
        orchestrator_module,
        "send_digest_completion_notification",
        lambda digest, user, *, api_key: False,
    )
    monkeypatch.setattr(orchestrator_module, "build_x_client", lambda credentials: None)


def _fetch_stub_per_topic(posts_by_topic: dict[str, list[RawPost]]):
    def fake(name, x_handles, **kwargs):
        return FetchResult(posts=posts_by_topic[name], error=None)

    return fake


@pytest.fixture()
def two_users_with_overlapping_topics(db_session, monkeypatch):
    """Seed User A and User B, each tracking a topic named identically
    (`SHARED_TOPIC_NAME`), then run a full digest for each — distinct post
    content per user so any cross-user bleed is trivially detectable."""
    user_a = _seed_user(db_session, email="user-a@example.com", handle="usera")
    user_b = _seed_user(db_session, email="user-b@example.com", handle="userb")
    topic_a = _seed_topic(db_session, user_a)
    topic_b = _seed_topic(db_session, user_b)

    # `run_digest` resolves each user's own X credentials (T067) — give both
    # users theirs so the orchestrator itself can run for each.
    for handle, suffix in (("usera", "USERA"), ("userb", "USERB")):
        monkeypatch.setenv(f"X_API_KEY__{suffix}", f"{handle}-key")
        monkeypatch.setenv(f"X_API_SECRET__{suffix}", f"{handle}-secret")
        monkeypatch.setenv(f"X_ACCESS_TOKEN__{suffix}", f"{handle}-token")
        monkeypatch.setenv(f"X_ACCESS_TOKEN_SECRET__{suffix}", f"{handle}-token-secret")

    posts_a = [_post(f"a-{i}", f"User A's post {i} about {SHARED_TOPIC_NAME}") for i in range(6)]
    posts_b = [_post(f"b-{i}", f"User B's post {i} about {SHARED_TOPIC_NAME}") for i in range(6)]
    monkeypatch.setattr(
        orchestrator_module,
        "get_fetch_provider",
        lambda **_: _fetch_stub_per_topic({SHARED_TOPIC_NAME: posts_a}),
    )
    digest_a = run_digest(
        db_session, user_a, [topic_a], run_type=DigestRunType.ON_DEMAND, config=_config()
    )

    monkeypatch.setattr(
        orchestrator_module,
        "get_fetch_provider",
        lambda **_: _fetch_stub_per_topic({SHARED_TOPIC_NAME: posts_b}),
    )
    digest_b = run_digest(
        db_session, user_b, [topic_b], run_type=DigestRunType.ON_DEMAND, config=_config()
    )

    return {
        "user_a": user_a,
        "user_b": user_b,
        "topic_a": topic_a,
        "topic_b": topic_b,
        "digest_a": digest_a,
        "digest_b": digest_b,
    }


# --- Acceptance Scenario 1: a user's run only ever uses their own data -----


def test_topics_with_the_same_name_never_collide_across_users(
    db_session, two_users_with_overlapping_topics
):
    fixtures = two_users_with_overlapping_topics
    user_a, user_b = fixtures["user_a"], fixtures["user_b"]

    topics_a = db_session.execute(scoped_select(Topic, user_a.id)).scalars().all()
    topics_b = db_session.execute(scoped_select(Topic, user_b.id)).scalars().all()

    assert [t.id for t in topics_a] == [fixtures["topic_a"].id]
    assert [t.id for t in topics_b] == [fixtures["topic_b"].id]
    assert topics_a[0].name == topics_b[0].name == SHARED_TOPIC_NAME
    assert topics_a[0].id != topics_b[0].id


@pytest.mark.parametrize(
    ("model", "fixture_key"),
    [
        (Digest, "digest_a"),
        (DraftPost, None),
        (PostingMode, None),
    ],
)
def test_direct_owner_models_are_scoped_per_user(
    db_session, two_users_with_overlapping_topics, model, fixture_key
):
    """Digest/DraftPost/PostingMode (data-model.md's directly-owned tables) —
    scoped_select for user A must never surface a row owned by user B."""
    fixtures = two_users_with_overlapping_topics
    user_a, user_b = fixtures["user_a"], fixtures["user_b"]

    rows_a = db_session.execute(scoped_select(model, user_a.id)).scalars().all()
    rows_b = db_session.execute(scoped_select(model, user_b.id)).scalars().all()

    assert rows_a, f"expected at least one {model.__name__} row for user A"
    assert rows_b, f"expected at least one {model.__name__} row for user B"
    ids_a = {row.id for row in rows_a}
    ids_b = {row.id for row in rows_b}
    assert ids_a.isdisjoint(ids_b)
    for row in rows_a:
        assert row.user_id == user_a.id
    for row in rows_b:
        assert row.user_id == user_b.id


@pytest.mark.parametrize("model", [DigestTopicResult, Theme, SourcePost, TopicBaselineSnapshot])
def test_transitively_owned_models_are_scoped_per_user(
    db_session, two_users_with_overlapping_topics, model
):
    """DigestTopicResult/Theme/SourcePost/TopicBaselineSnapshot (owned via a
    foreign-key chain up to Digest/Topic) — same guarantee, one join deeper."""
    fixtures = two_users_with_overlapping_topics
    user_a, user_b = fixtures["user_a"], fixtures["user_b"]

    rows_a = db_session.execute(scoped_select(model, user_a.id)).scalars().all()
    rows_b = db_session.execute(scoped_select(model, user_b.id)).scalars().all()

    assert rows_a, f"expected at least one {model.__name__} row for user A"
    assert rows_b, f"expected at least one {model.__name__} row for user B"
    ids_a = {row.id for row in rows_a}
    ids_b = {row.id for row in rows_b}
    assert ids_a.isdisjoint(ids_b)


def test_source_post_text_never_bleeds_between_users_despite_identical_topic_name(
    db_session, two_users_with_overlapping_topics
):
    fixtures = two_users_with_overlapping_topics
    user_a, user_b = fixtures["user_a"], fixtures["user_b"]

    posts_a = db_session.execute(scoped_select(SourcePost, user_a.id)).scalars().all()
    posts_b = db_session.execute(scoped_select(SourcePost, user_b.id)).scalars().all()

    assert all("User A's post" in p.text for p in posts_a)
    assert all("User B's post" in p.text for p in posts_b)


# --- Acceptance Scenario 2: no cross-user credential access ---------------


def test_x_credentials_never_cross_between_two_users(two_users_with_overlapping_topics):
    fixtures = two_users_with_overlapping_topics
    user_a, user_b = fixtures["user_a"], fixtures["user_b"]

    env = {
        "X_API_KEY__USERA": "a-key",
        "X_API_SECRET__USERA": "a-secret",
        "X_ACCESS_TOKEN__USERA": "a-token",
        "X_ACCESS_TOKEN_SECRET__USERA": "a-token-secret",
        "X_API_KEY__USERB": "b-key",
        "X_API_SECRET__USERB": "b-secret",
        "X_ACCESS_TOKEN__USERB": "b-token",
        "X_ACCESS_TOKEN_SECRET__USERB": "b-token-secret",
    }

    creds_a = load_x_credentials_for_user(user_a, env=env)
    creds_b = load_x_credentials_for_user(user_b, env=env)

    assert creds_a.api_key == "a-key"
    assert creds_b.api_key == "b-key"
    assert creds_a != creds_b


def test_a_user_with_no_credentials_configured_cannot_fall_back_to_the_others(
    two_users_with_overlapping_topics,
):
    """If only user B's credentials are configured, resolving user A's must
    fail loudly rather than silently reuse user B's (the exact leak FR-015
    forbids)."""
    fixtures = two_users_with_overlapping_topics
    user_a = fixtures["user_a"]

    env = {
        "X_API_KEY__USERB": "b-key",
        "X_API_SECRET__USERB": "b-secret",
        "X_ACCESS_TOKEN__USERB": "b-token",
        "X_ACCESS_TOKEN_SECRET__USERB": "b-token-secret",
    }

    with pytest.raises(ConfigError):
        load_x_credentials_for_user(user_a, env=env)


# --- Process identity: the CLI must never guess between two users ---------


def test_resolve_current_user_refuses_to_guess_with_two_users_and_no_selector(
    db_session, two_users_with_overlapping_topics
):
    with pytest.raises(NoCurrentUserError):
        resolve_current_user(db_session, env={})


def test_resolve_current_user_picks_the_selected_user_via_env_var(
    db_session, two_users_with_overlapping_topics
):
    fixtures = two_users_with_overlapping_topics
    user_a, user_b = fixtures["user_a"], fixtures["user_b"]

    resolved_a = resolve_current_user(db_session, env={"XHF_USER_EMAIL": user_a.email})
    resolved_b = resolve_current_user(db_session, env={"XHF_USER_EMAIL": user_b.email})

    assert resolved_a.id == user_a.id
    assert resolved_b.id == user_b.id


# --- CLI-level end-to-end: overlapping names, only-own-data everywhere -----


def _run_cli(cli_module, db_session, argv: list[str], monkeypatch, *, as_email: str) -> int:
    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(cli_module, "get_session", fake_get_session)
    monkeypatch.setenv("XHF_USER_EMAIL", as_email)
    return cli_module.main(argv)


def test_cli_topic_list_shows_only_the_selected_users_topic(
    db_session, two_users_with_overlapping_topics, monkeypatch, capsys
):
    fixtures = two_users_with_overlapping_topics
    user_a = fixtures["user_a"]

    exit_code = _run_cli(topic_cli, db_session, ["list"], monkeypatch, as_email=user_a.email)
    assert exit_code == 0

    out = capsys.readouterr().out
    assert SHARED_TOPIC_NAME in out
    # Only one line of topic output — user B's identically-named topic must
    # not also appear.
    assert out.count(SHARED_TOPIC_NAME) == 1


def test_cli_digest_show_for_user_a_digest_id_is_invisible_to_user_b(
    db_session, two_users_with_overlapping_topics, monkeypatch, capsys
):
    """User B attempting to `digest show` User A's digest id must be blocked
    by data isolation (spec.md Edge Cases: "What happens when a user attempts
    to access another user's data? The request must be blocked.")."""
    fixtures = two_users_with_overlapping_topics
    digest_a, user_b = fixtures["digest_a"], fixtures["user_b"]

    exit_code = _run_cli(
        digest_cli,
        db_session,
        ["show", str(digest_a.id)],
        monkeypatch,
        as_email=user_b.email,
    )

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "No digest found" in err


def test_cli_digest_show_for_user_a_digest_id_works_for_user_a(
    db_session, two_users_with_overlapping_topics, monkeypatch, capsys
):
    fixtures = two_users_with_overlapping_topics
    digest_a, user_a = fixtures["digest_a"], fixtures["user_a"]

    exit_code = _run_cli(
        digest_cli,
        db_session,
        ["show", str(digest_a.id)],
        monkeypatch,
        as_email=user_a.email,
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "User A's post" in out
    assert "User B's post" not in out


def test_cli_drafts_list_only_shows_the_selected_users_drafts(
    db_session, two_users_with_overlapping_topics, monkeypatch, capsys
):
    fixtures = two_users_with_overlapping_topics
    user_a, user_b = fixtures["user_a"], fixtures["user_b"]

    exit_code = _run_cli(drafts_cli, db_session, ["list"], monkeypatch, as_email=user_a.email)
    assert exit_code == 0
    out_a = capsys.readouterr().out

    exit_code = _run_cli(drafts_cli, db_session, ["list"], monkeypatch, as_email=user_b.email)
    assert exit_code == 0
    out_b = capsys.readouterr().out

    drafts_a = db_session.execute(scoped_select(DraftPost, user_a.id)).scalars().all()
    drafts_b = db_session.execute(scoped_select(DraftPost, user_b.id)).scalars().all()
    assert drafts_a and drafts_b

    for draft in drafts_a:
        assert str(draft.id) in out_a
        assert str(draft.id) not in out_b
    for draft in drafts_b:
        assert str(draft.id) in out_b
        assert str(draft.id) not in out_a


def test_cli_posting_mode_show_reflects_only_the_selected_users_posting_mode(
    db_session, two_users_with_overlapping_topics, monkeypatch, capsys
):
    fixtures = two_users_with_overlapping_topics
    user_a, user_b = fixtures["user_a"], fixtures["user_b"]

    mode_a = db_session.execute(scoped_select(PostingMode, user_a.id)).scalar_one()
    mode_b = db_session.execute(scoped_select(PostingMode, user_b.id)).scalar_one()
    mode_b.confidence_threshold = mode_a.confidence_threshold + 1
    db_session.commit()

    exit_code = _run_cli(
        posting_cli, db_session, ["mode", "show"], monkeypatch, as_email=user_a.email
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert f"confidence_threshold:      {mode_a.confidence_threshold}" in out
    assert f"confidence_threshold:      {mode_b.confidence_threshold}" not in out
