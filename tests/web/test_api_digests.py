"""Tests for `src/web/routers/digests.py` (specs/003-web-dashboard/plan.md §1).

List/detail tests seed the digest tables directly (same convention
tests/web/test_api_drafts.py uses). Background-job tests invoke the
`_run_digest_job` worker function directly via `registry.run`, bypassing
real `BackgroundTasks` scheduling, for deterministic, non-flaky polling
assertions (plan.md §5) — `run_digest`/`load_config` are monkeypatched at
the `src.web.routers.digests` import site, the same boundary
tests/integration/test_on_demand_digest.py stubs `get_fetch_provider` at.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

import src.web.routers.digests as digests_module
from src.cli.digest import CONFIDENCE_DISPLAY_THRESHOLD
from src.models.digest import Digest, DigestRunType, DigestStatus
from src.models.digest_topic_result import DigestTopicOutcome, DigestTopicResult
from src.models.source_post import FilterOutcome, SourcePost
from src.models.theme import Theme
from src.models.topic import Topic, TopicStatus
from src.web.jobs import registry


def _seed_digest_with_two_themes(db_session, user):
    """One topic, one THEMES_PRESENT DigestTopicResult, two Themes — one
    above CONFIDENCE_DISPLAY_THRESHOLD (kept by default), one below (hidden
    by default) — each with an example post, a non-example clustered post,
    and one excluded/unclustered post at the topic level."""
    topic = Topic(user_id=user.id, name="AAPL", x_handles=[], status=TopicStatus.ACTIVE)
    db_session.add(topic)
    db_session.flush()

    digest = Digest(
        user_id=user.id,
        run_type=DigestRunType.ON_DEMAND,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        status=DigestStatus.COMPLETED,
    )
    db_session.add(digest)
    db_session.flush()

    dtr = DigestTopicResult(
        digest_id=digest.id, topic_id=topic.id, outcome=DigestTopicOutcome.THEMES_PRESENT
    )
    db_session.add(dtr)
    db_session.flush()

    kept_theme = Theme(
        digest_topic_result_id=dtr.id,
        summary="Kept theme.",
        rationale="Above the confidence floor.",
        confidence_score=CONFIDENCE_DISPLAY_THRESHOLD + 10,
        is_spike=True,
        spike_ratio=3.5,
        cluster_post_count=2,
        rank=1,
    )
    hidden_theme = Theme(
        digest_topic_result_id=dtr.id,
        summary="Hidden theme.",
        rationale="Below the confidence floor.",
        confidence_score=CONFIDENCE_DISPLAY_THRESHOLD - 5,
        is_spike=False,
        spike_ratio=None,
        cluster_post_count=1,
        rank=2,
    )
    db_session.add_all([kept_theme, hidden_theme])
    db_session.flush()

    example_post = SourcePost(
        topic_id=topic.id,
        digest_topic_result_id=dtr.id,
        x_post_id="1",
        author_handle="alice",
        text="Example post.",
        posted_at=datetime.now(UTC),
        filter_outcome=FilterOutcome.KEPT,
        theme_id=kept_theme.id,
        is_example=True,
    )
    non_example_post = SourcePost(
        topic_id=topic.id,
        digest_topic_result_id=dtr.id,
        x_post_id="2",
        author_handle="bob",
        text="Non-example clustered post.",
        posted_at=datetime.now(UTC),
        filter_outcome=FilterOutcome.KEPT,
        theme_id=kept_theme.id,
        is_example=False,
    )
    excluded_post = SourcePost(
        topic_id=topic.id,
        digest_topic_result_id=dtr.id,
        x_post_id="3",
        author_handle="carol",
        text="Excluded post.",
        posted_at=datetime.now(UTC),
        filter_outcome=FilterOutcome.EXCLUDED_RULE,
        theme_id=None,
        is_example=False,
    )
    db_session.add_all([example_post, non_example_post, excluded_post])
    db_session.commit()
    return digest, topic, kept_theme, hidden_theme


def test_get_digests_lists_newest_first(authed_client, db_session, seed_user):
    older = Digest(
        user_id=seed_user.id,
        run_type=DigestRunType.SCHEDULED,
        started_at=datetime.now(UTC) - timedelta(days=1),
        status=DigestStatus.COMPLETED,
    )
    newer = Digest(
        user_id=seed_user.id,
        run_type=DigestRunType.ON_DEMAND,
        started_at=datetime.now(UTC),
        status=DigestStatus.COMPLETED,
    )
    db_session.add_all([older, newer])
    db_session.commit()

    response = authed_client.get("/api/digests")
    assert response.status_code == 200
    ids = [d["id"] for d in response.json()]
    assert ids == [str(newer.id), str(older.id)]


def test_get_digest_detail_default_view_hides_low_confidence_theme(
    authed_client, db_session, seed_user
):
    digest, _topic, kept_theme, _hidden_theme = _seed_digest_with_two_themes(db_session, seed_user)

    response = authed_client.get(f"/api/digests/{digest.id}")
    assert response.status_code == 200
    body = response.json()
    assert len(body["topics"]) == 1
    topic_result = body["topics"][0]
    assert topic_result["hidden_theme_count"] == 1
    assert [t["id"] for t in topic_result["themes"]] == [str(kept_theme.id)]

    theme = topic_result["themes"][0]
    assert len(theme["example_posts"]) == 1
    assert theme["example_posts"][0]["author_handle"] == "alice"
    # Non-full view never includes the full clustered-post drill-down.
    assert theme["source_posts"] is None
    assert topic_result["excluded_posts"] is None


def test_get_digest_detail_full_view_shows_everything(authed_client, db_session, seed_user):
    digest, _topic, kept_theme, hidden_theme = _seed_digest_with_two_themes(db_session, seed_user)

    response = authed_client.get(f"/api/digests/{digest.id}", params={"full": "true"})
    assert response.status_code == 200
    topic_result = response.json()["topics"][0]

    assert topic_result["hidden_theme_count"] == 0
    theme_ids = {t["id"] for t in topic_result["themes"]}
    assert theme_ids == {str(kept_theme.id), str(hidden_theme.id)}

    kept = next(t for t in topic_result["themes"] if t["id"] == str(kept_theme.id))
    assert kept["source_posts"] is not None
    assert {p["author_handle"] for p in kept["source_posts"]} == {"alice", "bob"}

    assert topic_result["excluded_posts"] is not None
    assert {p["author_handle"] for p in topic_result["excluded_posts"]} == {"carol"}


def test_get_digest_detail_unknown_id_is_404(authed_client, seed_user):
    response = authed_client.get("/api/digests/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_start_digest_run_returns_a_job_id(authed_client, seed_user):
    response = authed_client.post("/api/digests/run", json={})
    assert response.status_code == 202
    assert "job_id" in response.json()


@pytest.fixture()
def _fake_orchestrator(monkeypatch):
    """Stub `run_digest`/`load_config` at the exact names `digests.py`
    imports (`from ... import run_digest` / `load_config`) — the module-local
    binding, not the origin module, is what needs patching."""

    def fake_run_digest(session, user, topics, *, run_type, config):
        digest = Digest(
            user_id=user.id,
            run_type=run_type,
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            status=DigestStatus.COMPLETED,
        )
        session.add(digest)
        session.commit()
        return digest

    monkeypatch.setattr(digests_module, "run_digest", fake_run_digest)
    monkeypatch.setattr(digests_module, "load_config", lambda: object())


def _run_job_directly(db_session, *args) -> object:
    @contextmanager
    def fake_session_factory():
        yield db_session

    job = registry.create(kind="digest_run")
    registry.run(job, digests_module._run_digest_job, *args, fake_session_factory)
    return job


def test_digest_run_job_worker_completes_and_is_pollable(
    authed_client, db_session, seed_user, _fake_orchestrator
):
    topic = Topic(user_id=seed_user.id, name="AAPL", x_handles=[], status=TopicStatus.ACTIVE)
    db_session.add(topic)
    db_session.commit()

    job = _run_job_directly(db_session, seed_user.id, None)

    response = authed_client.get(f"/api/digests/jobs/{job.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["digest_id"] is not None
    assert body["error"] is None


def test_digest_run_job_worker_records_failure_when_no_active_topics(
    authed_client, db_session, seed_user, _fake_orchestrator
):
    job = _run_job_directly(db_session, seed_user.id, None)

    response = authed_client.get(f"/api/digests/jobs/{job.id}")
    body = response.json()
    assert body["status"] == "failed"
    assert "No active topics" in body["error"]


def test_digest_run_job_worker_rejects_an_unknown_topic_name(
    authed_client, db_session, seed_user, _fake_orchestrator
):
    job = _run_job_directly(db_session, seed_user.id, "NOPE")

    response = authed_client.get(f"/api/digests/jobs/{job.id}")
    body = response.json()
    assert body["status"] == "failed"
    assert "NOPE" in body["error"]


def test_get_digest_job_unknown_id_is_404(authed_client, seed_user):
    response = authed_client.get("/api/digests/jobs/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_digests_endpoints_require_auth(client):
    assert client.get("/api/digests").status_code == 401
    assert client.get("/api/digests/00000000-0000-0000-0000-000000000000").status_code == 401
    assert client.post("/api/digests/run", json={}).status_code == 401
    assert client.get("/api/digests/jobs/00000000-0000-0000-0000-000000000000").status_code == 401
