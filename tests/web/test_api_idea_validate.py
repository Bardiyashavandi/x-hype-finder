"""Tests for `src/web/routers/idea_validate.py` (specs/003-web-dashboard/plan.md
§0.B, §1).

Worker tests reuse the same hermetic-pipeline stubbing convention
tests/integration/test_idea_validation_flow.py already established
(monkeypatching `src.cli.idea_validate`'s module-level bindings for
Fetch/Cluster/Claude), then invoke `run_idea_validation_structured` directly
via `registry.run` — bypassing real `BackgroundTasks` scheduling, per
plan.md §5 — rather than going through the POST endpoint.
"""

from __future__ import annotations

from datetime import UTC, datetime

import src.cli.idea_validate as idea_validate_module
import src.web.routers.idea_validate as idea_validate_router
from src.agent.validate_summarize import ValidationSummarizeResult
from src.cli.idea_validate import run_idea_validation_structured
from src.config import Config, ConfigError
from src.pipeline.cluster import ThemeCandidate
from src.pipeline.fetch import AuthorMetadata, FetchError, FetchErrorKind, FetchResult, RawPost
from src.pipeline.filter import filter_posts
from src.pipeline.idea_query_builder import IdeaValidationQuery
from src.web.jobs import registry

API_KEY = "test-anthropic-key"
MODEL = "claude-sonnet-5"
SINCE = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
UNTIL = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _config() -> Config:
    return Config(
        twitterapi_io_key="",
        anthropic_api_key=API_KEY,
        resend_api_key="test-resend-key",
        claude_model=MODEL,
    )


def _query(phrases: list[str]) -> IdeaValidationQuery:
    return IdeaValidationQuery(phrases=phrases, exclude_terms=[], since=SINCE, until=UNTIL)


def _orthogonal_embed_fn(texts: list[str]) -> list[list[float]]:
    n = len(texts)
    return [[1.0 if i == j else 0.0 for i in range(n)] for j in range(n)]


def _all_one_group_cluster(posts: list[RawPost]) -> list[ThemeCandidate]:
    return [ThemeCandidate(posts=tuple(posts))] if posts else []


def _post(post_id: str, text: str, *, author: str) -> RawPost:
    return RawPost(
        x_post_id=post_id,
        author_handle=author,
        text=text,
        posted_at=UNTIL,
        author_metadata=AuthorMetadata(
            account_age_days=500, followers_count=2000, following_count=300, post_frequency=1.5
        ),
    )


def test_get_idea_validate_defaults(authed_client, seed_user):
    response = authed_client.get("/api/idea-validate")
    assert response.status_code == 200
    assert response.json() == {"default_lookback_hours": 24}


def test_post_idea_validate_rejects_empty_phrases(authed_client, seed_user):
    response = authed_client.post("/api/idea-validate", json={"phrases": []})
    assert response.status_code == 400


def test_post_idea_validate_surfaces_a_missing_credential_as_500(
    authed_client, seed_user, monkeypatch
):
    def raise_config_error():
        raise ConfigError("Missing required environment variable(s): ANTHROPIC_API_KEY.")

    monkeypatch.setattr(idea_validate_router, "load_config", raise_config_error)

    response = authed_client.post("/api/idea-validate", json={"phrases": ["can't find sublet"]})
    assert response.status_code == 500


def test_post_idea_validate_returns_a_job_id(authed_client, seed_user, monkeypatch):
    monkeypatch.setattr(idea_validate_router, "load_config", _config)

    response = authed_client.post("/api/idea-validate", json={"phrases": ["can't find sublet"]})
    assert response.status_code == 202
    assert "job_id" in response.json()


def test_idea_validate_job_worker_completes_with_a_structured_readout(
    authed_client, seed_user, monkeypatch
):
    posts = [
        _post("1", "Can't find a sublet anywhere in this city", author="alice"),
        _post("2", "Sublet is a nightmare here, nobody wants short-term", author="bob"),
    ]

    def fetch_stub(query: str, *, max_posts=None, session=None):
        return FetchResult(posts=posts, error=None)

    monkeypatch.setattr(
        idea_validate_module, "get_fetch_provider_for_query", lambda **_: fetch_stub
    )
    monkeypatch.setattr(
        idea_validate_module,
        "filter_posts",
        lambda posts: filter_posts(posts, embed_fn=_orthogonal_embed_fn),
    )
    monkeypatch.setattr(idea_validate_module, "cluster_posts", _all_one_group_cluster)
    monkeypatch.setattr(
        idea_validate_module,
        "summarize_validation_theme",
        lambda data, *, api_key, model: ValidationSummarizeResult(
            summary="People struggle to find short-term sublets.",
            representative_ask="I just need a place for a few months.",
            recurrence_signal="recurring",
        ),
    )
    monkeypatch.setattr(
        idea_validate_module,
        "synthesize_validation_verdict",
        lambda data, *, api_key, model: type(
            "V", (), {"verdict": "A real, validated problem worth pursuing."}
        )(),
    )

    query = _query(["can't find sublet"])
    job = registry.create(kind="idea_validate_run")
    registry.run(
        job, run_idea_validation_structured, query, anthropic_api_key=API_KEY, claude_model=MODEL
    )

    response = authed_client.get(f"/api/idea-validate/jobs/{job.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["error"] is None
    readout = body["readout"]
    assert readout["fetch_error"] is None
    assert readout["verdict"] == "A real, validated problem worth pursuing."
    assert readout["signal_strength"]["total_relevant_count"] == 2
    assert len(readout["themes"]) == 1
    assert readout["themes"][0]["recurrence_signal"] == "recurring"


def test_idea_validate_job_worker_records_a_fetch_failure(authed_client, seed_user, monkeypatch):
    def failing_fetch(query: str, *, max_posts=None, session=None):
        return FetchResult(
            posts=None, error=FetchError(kind=FetchErrorKind.RATE_LIMITED, detail="rate limited")
        )

    monkeypatch.setattr(
        idea_validate_module, "get_fetch_provider_for_query", lambda **_: failing_fetch
    )

    query = _query(["can't find sublet"])
    job = registry.create(kind="idea_validate_run")
    registry.run(
        job, run_idea_validation_structured, query, anthropic_api_key=API_KEY, claude_model=MODEL
    )

    response = authed_client.get(f"/api/idea-validate/jobs/{job.id}")
    body = response.json()
    assert body["status"] == "completed"  # the pipeline itself never raises on a Fetch error
    readout = body["readout"]
    assert "rate limited" in readout["fetch_error"]
    assert readout["themes"] == []


def test_get_idea_validate_job_unknown_id_is_404(authed_client, seed_user):
    response = authed_client.get("/api/idea-validate/jobs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_idea_validate_endpoints_require_auth(client):
    assert client.get("/api/idea-validate").status_code == 401
    assert client.post("/api/idea-validate", json={"phrases": ["x"]}).status_code == 401
    assert (
        client.get("/api/idea-validate/jobs/00000000-0000-0000-0000-000000000000").status_code
        == 401
    )
