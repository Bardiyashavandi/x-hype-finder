"""Tests for `src/web/routers/drafts.py` — wraps `list_drafts`/`mark_published`
(src/cli/drafts.py, specs/003-web-dashboard/plan.md §0.A, §1).
"""

from __future__ import annotations

from datetime import UTC, datetime

from src.models.digest import Digest, DigestRunType, DigestStatus
from src.models.digest_topic_result import DigestTopicOutcome, DigestTopicResult
from src.models.draft_post import DraftPost, DraftPostStatus
from src.models.theme import Theme
from src.models.topic import Topic, TopicStatus


def _seed_draft(db_session, user, *, status: DraftPostStatus, confidence: int = 80) -> DraftPost:
    topic = Topic(user_id=user.id, name="AAPL", x_handles=[], status=TopicStatus.ACTIVE)
    db_session.add(topic)
    db_session.flush()

    digest = Digest(
        user_id=user.id,
        run_type=DigestRunType.ON_DEMAND,
        started_at=datetime.now(UTC),
        status=DigestStatus.COMPLETED,
    )
    db_session.add(digest)
    db_session.flush()

    dtr = DigestTopicResult(
        digest_id=digest.id, topic_id=topic.id, outcome=DigestTopicOutcome.THEMES_PRESENT
    )
    db_session.add(dtr)
    db_session.flush()

    theme = Theme(
        digest_topic_result_id=dtr.id,
        summary="A summary.",
        rationale="A rationale.",
        confidence_score=confidence,
        is_spike=True,
        spike_ratio=3.0,
        cluster_post_count=5,
        rank=1,
    )
    db_session.add(theme)
    db_session.flush()

    draft = DraftPost(
        theme_id=theme.id,
        user_id=user.id,
        draft_text="A draft.",
        confidence_score=confidence,
        status=status,
    )
    db_session.add(draft)
    db_session.commit()
    return draft


def test_get_drafts_lists_all_of_this_users_drafts(authed_client, db_session, seed_user):
    _seed_draft(db_session, seed_user, status=DraftPostStatus.HELD_MANUAL)
    _seed_draft(db_session, seed_user, status=DraftPostStatus.HELD_BELOW_THRESHOLD)

    response = authed_client.get("/api/drafts")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_get_drafts_filters_by_status(authed_client, db_session, seed_user):
    _seed_draft(db_session, seed_user, status=DraftPostStatus.HELD_MANUAL)
    _seed_draft(db_session, seed_user, status=DraftPostStatus.HELD_BELOW_THRESHOLD)

    response = authed_client.get("/api/drafts", params={"status": "held_manual"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["status"] == "held_manual"


def test_get_drafts_rejects_an_unknown_status(authed_client, seed_user):
    response = authed_client.get("/api/drafts", params={"status": "not_a_real_status"})
    assert response.status_code == 400


def test_publish_draft_marks_a_held_manual_draft_published(authed_client, db_session, seed_user):
    draft = _seed_draft(db_session, seed_user, status=DraftPostStatus.HELD_MANUAL)

    response = authed_client.post(f"/api/drafts/{draft.id}/publish", json={"confirmed": True})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "published_manual"
    assert body["published_at"] is not None
    # Mirrors CLI's mark_published: never calls the X API, so no tweet id/url.
    assert body["tweet_id"] is None
    assert body["tweet_url"] is None


def test_publish_draft_requires_the_confirmed_literal_true(authed_client, db_session, seed_user):
    draft = _seed_draft(db_session, seed_user, status=DraftPostStatus.HELD_MANUAL)

    response = authed_client.post(f"/api/drafts/{draft.id}/publish", json={"confirmed": False})
    assert response.status_code == 422

    response = authed_client.post(f"/api/drafts/{draft.id}/publish", json={})
    assert response.status_code == 422


def test_publish_draft_rejects_a_non_held_manual_draft(authed_client, db_session, seed_user):
    draft = _seed_draft(db_session, seed_user, status=DraftPostStatus.HELD_BELOW_THRESHOLD)

    response = authed_client.post(f"/api/drafts/{draft.id}/publish", json={"confirmed": True})
    assert response.status_code == 409


def test_publish_unknown_draft_id_is_404(authed_client, seed_user):
    response = authed_client.post(
        "/api/drafts/00000000-0000-0000-0000-000000000000/publish", json={"confirmed": True}
    )
    assert response.status_code == 404


def test_drafts_endpoints_require_auth(client):
    assert client.get("/api/drafts").status_code == 401
    assert (
        client.post(
            "/api/drafts/00000000-0000-0000-0000-000000000000/publish", json={"confirmed": True}
        ).status_code
        == 401
    )
