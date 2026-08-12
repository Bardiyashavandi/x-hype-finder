"""End-to-end integration test for Idea Validation mode (tasks.md T010,
quickstart.md Scenarios 1, 3, 4; spec.md §7).

Runs Query Construction -> Fetch -> Relevance Filter -> Bot/Noise Filter ->
Signal Strength -> Cluster -> Validate Summarize -> Validation Readout
against a synthetic "sublet" problem-space fixture (spec.md §2, §5.2), with
Fetch and Claude both mocked — no live network call. Fetch is mocked at the
`get_fetch_provider_for_query` abstraction boundary (src/pipeline/fetch_provider.py),
the same boundary orchestrator.py's own tests stub `get_fetch_provider` at
(tests/integration/test_on_demand_digest.py) — this locks in that
`idea_validate.py` goes through the shared FETCH_PROVIDER abstraction rather
than a hardcoded provider. Asserts the readout is non-empty for the
signal-present case, explicitly states "no meaningful signal found" for the
zero-signal case, surfaces a Fetch error rather than crashing, drops one
failed theme without blanking the whole readout, and that this mode never
writes to any application-owned table (spec.md §3 non-goals,
contracts/cli-commands.md).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

import src.cli.idea_validate as idea_validate_module
from src.agent.validate_summarize import ValidationSummarizeResult
from src.cli.idea_validate import run_idea_validation
from src.models.digest import Digest
from src.models.draft_post import DraftPost
from src.models.source_post import SourcePost
from src.models.theme import Theme
from src.pipeline.fetch import AuthorMetadata, FetchError, FetchErrorKind, FetchResult, RawPost
from src.pipeline.filter import filter_posts
from src.pipeline.idea_query_builder import IdeaValidationQuery

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
API_KEY = "test-anthropic-key"
MODEL = "claude-sonnet-5"


def _query(phrases: list[str], exclude_terms: list[str] | None = None) -> IdeaValidationQuery:
    return IdeaValidationQuery(
        phrases=phrases,
        exclude_terms=exclude_terms or [],
        since=NOW - timedelta(days=1),
        until=NOW,
    )


def _post(post_id: str, text: str, *, author: str, posted_at: datetime = NOW) -> RawPost:
    return RawPost(
        x_post_id=post_id,
        author_handle=author,
        text=text,
        posted_at=posted_at,
        author_metadata=AuthorMetadata(
            account_age_days=500, followers_count=2000, following_count=300, post_frequency=1.5
        ),
    )


def _orthogonal_embed_fn(texts: list[str]) -> list[list[float]]:
    n = len(texts)
    return [[1.0 if i == j else 0.0 for i in range(n)] for j in range(n)]


def _all_one_group_cluster(posts):
    from src.pipeline.cluster import ThemeCandidate

    return [ThemeCandidate(posts=tuple(posts))] if posts else []


@pytest.fixture(autouse=True)
def _hermetic_pipeline(monkeypatch):
    """No live Ollama/Claude/network calls — Filter's own Tier 1/Tier 2
    logic still runs for real, same pattern as
    tests/integration/test_on_demand_digest.py's `_hermetic_pipeline`."""
    monkeypatch.setattr(
        idea_validate_module,
        "filter_posts",
        lambda posts: filter_posts(posts, embed_fn=_orthogonal_embed_fn),
    )
    monkeypatch.setattr(idea_validate_module, "cluster_posts", _all_one_group_cluster)


def _patch_fetch_provider(monkeypatch, fake_provider):
    """Stub the `get_fetch_provider_for_query()` resolver itself (not the
    concrete provider module), the same abstraction-boundary convention
    orchestrator.py's tests stub `get_fetch_provider` at — so these tests
    stay agnostic to which concrete provider FETCH_PROVIDER resolves to."""
    monkeypatch.setattr(
        idea_validate_module, "get_fetch_provider_for_query", lambda **_: fake_provider
    )


def _fetch_stub(posts: list[RawPost]):
    def fake(query: str, *, max_posts=None, session=None):
        return FetchResult(posts=posts, error=None)

    return fake


def _summarize_stub(result: ValidationSummarizeResult):
    def fake(data, *, api_key, model, client=None):
        assert api_key == API_KEY
        assert model == MODEL
        return result

    return fake


def _table_row_counts(db_session) -> dict[str, int]:
    return {
        "digests": len(db_session.execute(select(Digest)).scalars().all()),
        "themes": len(db_session.execute(select(Theme)).scalars().all()),
        "source_posts": len(db_session.execute(select(SourcePost)).scalars().all()),
        "draft_posts": len(db_session.execute(select(DraftPost)).scalars().all()),
    }


def test_fetch_goes_through_the_shared_fetch_provider_abstraction(db_session, monkeypatch):
    """Locks in that idea_validate.py calls
    `src.pipeline.fetch_provider.get_fetch_provider_for_query` — the same
    `FETCH_PROVIDER`-respecting abstraction every other command uses via
    `get_fetch_provider` — rather than hardcoding a concrete provider's
    `fetch_posts_for_query` directly."""
    resolver_calls = []
    query_calls = []

    def fake_resolver(**kwargs):
        resolver_calls.append(kwargs)

        def fake_provider(query, **call_kwargs):
            query_calls.append(query)
            return FetchResult(posts=[], error=None)

        return fake_provider

    monkeypatch.setattr(idea_validate_module, "get_fetch_provider_for_query", fake_resolver)

    query = _query(["can't find sublet"])
    run_idea_validation(query, anthropic_api_key=API_KEY, claude_model=MODEL)

    assert len(resolver_calls) == 1
    assert len(query_calls) == 1
    assert "can't find sublet" in query_calls[0]


def test_signal_present_case_produces_a_non_empty_readout_with_no_db_writes(
    db_session, monkeypatch
):
    before = _table_row_counts(db_session)

    sublet_posts = [
        _post("1", "Can't find a sublet anywhere in this city, it's impossible", author="alice"),
        _post("2", "Sublet is a nightmare here, nobody wants short-term", author="bob"),
        _post("3", "No easy way to sublet an apartment for just a summer", author="carol"),
    ]
    _patch_fetch_provider(monkeypatch, _fetch_stub(sublet_posts))
    monkeypatch.setattr(
        idea_validate_module,
        "summarize_validation_theme",
        _summarize_stub(
            ValidationSummarizeResult(
                summary="People struggle to find short-term sublets when moving to a new city.",
                representative_ask="I just need a place for a few months, not a full year lease.",
                recurrence_signal="recurring",
            )
        ),
    )

    query = _query(
        ["can't find sublet", "no easy way to sublet", "sublet is a nightmare"],
        ["sublet.com"],
    )

    rendered = run_idea_validation(query, anthropic_api_key=API_KEY, claude_model=MODEL)

    assert "No meaningful signal found" not in rendered
    assert "total_relevant_count: 3" in rendered
    assert "recurring" in rendered
    assert "struggle to find short-term sublets" in rendered

    after = _table_row_counts(db_session)
    assert after == before


def test_zero_signal_case_states_no_meaningful_signal_found_explicitly(db_session, monkeypatch):
    before = _table_row_counts(db_session)

    _patch_fetch_provider(monkeypatch, _fetch_stub([]))

    query = _query(["a nonsense phrase absolutely nobody would ever post about ever"])

    rendered = run_idea_validation(query, anthropic_api_key=API_KEY, claude_model=MODEL)

    assert "No meaningful signal found" in rendered
    assert rendered.strip() != ""

    after = _table_row_counts(db_session)
    assert after == before


def test_fetch_error_is_surfaced_explicitly_not_a_crash_or_empty_output(db_session, monkeypatch):
    before = _table_row_counts(db_session)

    def failing_fetch(query: str, *, max_posts=None, session=None):
        return FetchResult(
            posts=None,
            error=FetchError(kind=FetchErrorKind.RATE_LIMITED, detail="rate limited by provider"),
        )

    _patch_fetch_provider(monkeypatch, failing_fetch)

    query = _query(["can't find sublet"])

    rendered = run_idea_validation(query, anthropic_api_key=API_KEY, claude_model=MODEL)

    assert "Fetch error" in rendered
    assert "rate limited by provider" in rendered
    assert rendered.strip() != ""

    after = _table_row_counts(db_session)
    assert after == before


def test_single_theme_summarize_failure_drops_only_that_theme(db_session, monkeypatch):
    """Two clusters worth of posts (two distinct-enough groups so Cluster
    doesn't merge them); one Validate Summarize call fails, the other
    succeeds — the readout still completes with the surviving theme rather
    than the whole run failing (contracts/cli-commands.md § Errors)."""
    before = _table_row_counts(db_session)

    posts = [
        _post("1", "Can't find a sublet in this city no matter what", author="alice"),
        _post("2", "Sublet hunting has been a total nightmare lately", author="bob"),
    ]
    _patch_fetch_provider(monkeypatch, _fetch_stub(posts))

    def two_groups_cluster(posts):
        from src.pipeline.cluster import ThemeCandidate

        return [ThemeCandidate(posts=(posts[0],)), ThemeCandidate(posts=(posts[1],))]

    monkeypatch.setattr(idea_validate_module, "cluster_posts", two_groups_cluster)

    from src.agent.validate_summarize import ValidateSummarizeError

    call_count = {"n": 0}

    def flaky_summarize(data, *, api_key, model, client=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ValidateSummarizeError("simulated persistent Claude failure")
        return ValidationSummarizeResult(
            summary="The surviving theme's summary.",
            representative_ask="The surviving theme's ask.",
            recurrence_signal="emerging",
        )

    monkeypatch.setattr(idea_validate_module, "summarize_validation_theme", flaky_summarize)

    query = _query(["can't find sublet", "sublet is a nightmare"])

    rendered = run_idea_validation(query, anthropic_api_key=API_KEY, claude_model=MODEL)

    assert "No meaningful signal found" not in rendered
    assert "The surviving theme's summary." in rendered
    assert rendered.count("recurrence_signal=") == 1

    after = _table_row_counts(db_session)
    assert after == before
