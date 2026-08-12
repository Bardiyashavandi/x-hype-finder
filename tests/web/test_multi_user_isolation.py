"""Web-API-level multi-user data isolation (User Story 5 / FR-015,
specs/003-web-dashboard) — the HTTP-facing counterpart of
tests/integration/test_multi_user_isolation.py's CLI-level test.

Now that the dashboard has real per-user login (`GET /api/auth/me` resolves
the session's stored `user_id` to an actual `User` row, src/web/deps.py's
`get_current_user`), this proves the same guarantee holds end-to-end over
HTTP: each logged-in user's session only ever sees their own topics,
digests, and drafts — even when two users track a topic with the identical
name, and even when one user requests the other's row by id directly.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.models.digest import Digest, DigestRunType, DigestStatus
from src.models.digest_topic_result import DigestTopicOutcome, DigestTopicResult
from src.models.draft_post import DraftPost, DraftPostStatus
from src.models.theme import Theme
from src.models.topic import Topic, TopicStatus
from src.models.user import User
from src.utils.password import hash_password

PASSWORD_A = "user-a-password"
PASSWORD_B = "user-b-password"
# Both users track a topic with the SAME name — the sharpest version of "did
# this leak," since a naive unscoped query would happily return either row
# for either user.
SHARED_TOPIC_NAME = "AAPL"


@pytest.fixture()
def user_a(db_session) -> User:
    user = User(
        email="user-a@example.com",
        x_account_handle="user_a",
        password_hash=hash_password(PASSWORD_A),
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def user_b(db_session) -> User:
    user = User(
        email="user-b@example.com",
        x_account_handle="user_b",
        password_hash=hash_password(PASSWORD_B),
    )
    db_session.add(user)
    db_session.flush()
    return user


def _seed_topic_digest_and_draft(
    db_session, user: User, *, topic_name: str
) -> tuple[Topic, Digest, DraftPost]:
    topic = Topic(user_id=user.id, name=topic_name, x_handles=[], status=TopicStatus.ACTIVE)
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
        summary=f"Summary for {user.email}.",
        rationale="A rationale.",
        confidence_score=80,
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
        draft_text=f"Draft for {user.email}.",
        confidence_score=80,
        status=DraftPostStatus.HELD_MANUAL,
    )
    db_session.add(draft)
    db_session.commit()
    return topic, digest, draft


def _login(app, email: str, password: str) -> TestClient:
    # A fresh TestClient per user — separate cookie jars against the *same*
    # `app` (and therefore the same overridden `db_session`), mirroring two
    # different browsers logged in as two different people.
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    return client


@pytest.fixture()
def seeded(db_session, app, user_a, user_b):
    topic_a, digest_a, draft_a = _seed_topic_digest_and_draft(
        db_session, user_a, topic_name=SHARED_TOPIC_NAME
    )
    topic_b, digest_b, draft_b = _seed_topic_digest_and_draft(
        db_session, user_b, topic_name=SHARED_TOPIC_NAME
    )
    client_a = _login(app, user_a.email, PASSWORD_A)
    client_b = _login(app, user_b.email, PASSWORD_B)
    return {
        "client_a": client_a,
        "client_b": client_b,
        "topic_a": topic_a,
        "topic_b": topic_b,
        "digest_a": digest_a,
        "digest_b": digest_b,
        "draft_a": draft_a,
        "draft_b": draft_b,
    }


def test_get_topics_only_returns_the_logged_in_users_topic(seeded):
    topics_a = seeded["client_a"].get("/api/topics").json()
    topics_b = seeded["client_b"].get("/api/topics").json()

    assert [t["id"] for t in topics_a] == [str(seeded["topic_a"].id)]
    assert [t["id"] for t in topics_b] == [str(seeded["topic_b"].id)]
    # Same name on both sides — the id, not the name, is what proves isolation.
    assert topics_a[0]["name"] == topics_b[0]["name"] == SHARED_TOPIC_NAME


def test_get_digests_only_returns_the_logged_in_users_digest(seeded):
    digests_a = seeded["client_a"].get("/api/digests").json()
    digests_b = seeded["client_b"].get("/api/digests").json()

    assert [d["id"] for d in digests_a] == [str(seeded["digest_a"].id)]
    assert [d["id"] for d in digests_b] == [str(seeded["digest_b"].id)]


def test_get_drafts_only_returns_the_logged_in_users_draft(seeded):
    drafts_a = seeded["client_a"].get("/api/drafts").json()
    drafts_b = seeded["client_b"].get("/api/drafts").json()

    assert [d["id"] for d in drafts_a] == [str(seeded["draft_a"].id)]
    assert [d["id"] for d in drafts_b] == [str(seeded["draft_b"].id)]


def test_get_another_users_digest_by_id_is_404_not_their_data(seeded):
    response = seeded["client_a"].get(f"/api/digests/{seeded['digest_b'].id}")
    assert response.status_code == 404

    # And the reverse, for good measure.
    response = seeded["client_b"].get(f"/api/digests/{seeded['digest_a'].id}")
    assert response.status_code == 404


def test_publish_another_users_draft_by_id_is_404_not_a_leaked_mutation(seeded):
    response = seeded["client_a"].post(
        f"/api/drafts/{seeded['draft_b'].id}/publish", json={"confirmed": True}
    )
    assert response.status_code == 404

    # Confirm it genuinely wasn't touched, not just that the response was 404.
    still_held = seeded["client_b"].get("/api/drafts").json()
    assert still_held[0]["status"] == "held_manual"


def test_each_clients_session_only_authenticates_as_its_own_user(seeded):
    me_a = seeded["client_a"].get("/api/auth/me").json()
    me_b = seeded["client_b"].get("/api/auth/me").json()

    assert me_a["email"] == "user-a@example.com"
    assert me_b["email"] == "user-b@example.com"
