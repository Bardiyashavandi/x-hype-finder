"""Tests for `src/web/routers/topics.py` — wraps `add_topic`/`remove_topic`/
`list_topics` (src/cli/topic.py, specs/003-web-dashboard/plan.md §1).
"""

from __future__ import annotations

from sqlalchemy import select

from src.models.topic import Topic, TopicStatus


def test_get_topics_lists_only_this_users_active_topics(authed_client, db_session, seed_user):
    active = Topic(user_id=seed_user.id, name="AAPL", x_handles=[], status=TopicStatus.ACTIVE)
    removed = Topic(user_id=seed_user.id, name="MSFT", x_handles=[], status=TopicStatus.REMOVED)
    db_session.add_all([active, removed])
    db_session.commit()

    response = authed_client.get("/api/topics")
    assert response.status_code == 200
    names = [t["name"] for t in response.json()]
    assert names == ["AAPL"]


def test_create_topic_adds_an_active_topic(authed_client, db_session, seed_user):
    response = authed_client.post("/api/topics", json={"name": "AAPL", "handles": ["apple"]})
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "AAPL"
    assert body["x_handles"] == ["apple"]
    assert body["status"] == "active"

    stored = db_session.execute(select(Topic).where(Topic.name == "AAPL")).scalar_one()
    assert stored.user_id == seed_user.id


def test_create_topic_rejects_a_duplicate_active_name(authed_client, db_session, seed_user):
    existing = Topic(user_id=seed_user.id, name="AAPL", x_handles=[], status=TopicStatus.ACTIVE)
    db_session.add(existing)
    db_session.commit()

    response = authed_client.post("/api/topics", json={"name": "AAPL"})
    assert response.status_code == 400
    assert "already active" in response.json()["detail"]


def test_delete_topic_soft_deletes_it(authed_client, db_session, seed_user):
    topic = Topic(user_id=seed_user.id, name="AAPL", x_handles=[], status=TopicStatus.ACTIVE)
    db_session.add(topic)
    db_session.commit()

    response = authed_client.delete(f"/api/topics/{topic.id}")
    assert response.status_code == 200
    assert response.json()["status"] == "removed"

    db_session.refresh(topic)
    assert topic.status == TopicStatus.REMOVED


def test_delete_unknown_topic_id_is_404(authed_client, seed_user):
    response = authed_client.delete("/api/topics/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_topics_endpoints_require_auth(client):
    assert client.get("/api/topics").status_code == 401
    assert client.post("/api/topics", json={"name": "AAPL"}).status_code == 401
    assert client.delete("/api/topics/00000000-0000-0000-0000-000000000000").status_code == 401
