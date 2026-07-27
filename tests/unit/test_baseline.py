"""Unit tests for SourcePost retention pruning (tasks.md T042/T070, FR-020,
data-model.md § SourcePost).

Covers both halves of retention and the distinction between them
(/speckit-analyze finding D1): `prune_source_posts_for_topic` is scoped to
one topic (the inline per-run half); `prune_stale_source_posts` sweeps every
topic at once (the standalone periodic half) and is what this file's new
coverage (T070) focuses on.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from src.models.source_post import FilterOutcome, SourcePost
from src.models.topic import Topic, TopicStatus
from src.models.user import User
from src.pipeline.baseline import (
    RETENTION_WINDOW,
    prune_source_posts_for_topic,
    prune_stale_source_posts,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def _seed_user(session) -> User:
    user = User(email="pilot@example.com", x_account_handle="pilot")
    session.add(user)
    session.flush()
    return user


def _seed_topic(session, user: User, name: str) -> Topic:
    topic = Topic(
        user_id=user.id,
        name=name,
        x_handles=[],
        status=TopicStatus.ACTIVE,
        first_tracked_at=NOW - timedelta(days=60),
    )
    session.add(topic)
    session.flush()
    return topic


def _seed_post(session, topic: Topic, *, posted_at: datetime) -> SourcePost:
    post = SourcePost(
        topic_id=topic.id,
        digest_topic_result_id=uuid.uuid4(),
        x_post_id=str(uuid.uuid4()),
        author_handle="someone",
        text="a post",
        posted_at=posted_at,
        filter_outcome=FilterOutcome.KEPT,
    )
    session.add(post)
    session.flush()
    return post


# --- prune_stale_source_posts (T070: standalone, all-topics sweep) --------


def test_sweep_deletes_rows_past_the_retention_window_across_every_topic(db_session):
    user = _seed_user(db_session)
    topic_a = _seed_topic(db_session, user, "AAPL")
    topic_b = _seed_topic(db_session, user, "MSFT")

    stale_a_id = _seed_post(
        db_session, topic_a, posted_at=NOW - RETENTION_WINDOW - timedelta(days=1)
    ).id
    stale_b_id = _seed_post(
        db_session, topic_b, posted_at=NOW - RETENTION_WINDOW - timedelta(days=5)
    ).id
    fresh_a_id = _seed_post(db_session, topic_a, posted_at=NOW - timedelta(days=1)).id
    db_session.commit()

    deleted = prune_stale_source_posts(db_session, as_of=NOW)
    db_session.commit()

    assert deleted == 2
    remaining_ids = {p.id for p in db_session.execute(select(SourcePost)).scalars().all()}
    assert remaining_ids == {fresh_a_id}
    assert stale_a_id not in remaining_ids
    assert stale_b_id not in remaining_ids


def test_sweep_keeps_rows_exactly_at_or_within_the_window(db_session):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user, "AAPL")
    just_within = _seed_post(
        db_session, topic, posted_at=NOW - RETENTION_WINDOW + timedelta(hours=1)
    )
    db_session.commit()

    deleted = prune_stale_source_posts(db_session, as_of=NOW)

    assert deleted == 0
    assert db_session.get(SourcePost, just_within.id) is not None


def test_sweep_is_a_no_op_when_nothing_is_stale(db_session):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user, "AAPL")
    _seed_post(db_session, topic, posted_at=NOW - timedelta(days=1))
    db_session.commit()

    assert prune_stale_source_posts(db_session, as_of=NOW) == 0


def test_sweep_honors_a_custom_retention_window(db_session):
    user = _seed_user(db_session)
    topic = _seed_topic(db_session, user, "AAPL")
    post_id = _seed_post(db_session, topic, posted_at=NOW - timedelta(days=8)).id
    db_session.commit()

    # Default 30-day window would keep this row; a custom 7-day window prunes it.
    assert prune_stale_source_posts(db_session, as_of=NOW) == 0
    deleted = prune_stale_source_posts(db_session, as_of=NOW, retention_window=timedelta(days=7))
    assert deleted == 1
    assert db_session.get(SourcePost, post_id) is None


# --- the T042/T070 distinction: per-topic prune never touches other topics -


def test_per_topic_prune_never_touches_a_different_topics_stale_rows(db_session):
    """Confirms prune_source_posts_for_topic (T042) is scoped to one topic —
    the exact gap prune_stale_source_posts (T070) exists to cover for topics
    other than the one a given run just processed."""
    user = _seed_user(db_session)
    topic_a = _seed_topic(db_session, user, "AAPL")
    topic_b = _seed_topic(db_session, user, "MSFT")
    stale_a_id = _seed_post(
        db_session, topic_a, posted_at=NOW - RETENTION_WINDOW - timedelta(days=1)
    ).id
    stale_b_id = _seed_post(
        db_session, topic_b, posted_at=NOW - RETENTION_WINDOW - timedelta(days=1)
    ).id
    db_session.commit()

    deleted = prune_source_posts_for_topic(db_session, topic_a.id, as_of=NOW)
    db_session.commit()

    assert deleted == 1
    assert db_session.get(SourcePost, stale_a_id) is None
    assert db_session.get(SourcePost, stale_b_id) is not None  # left for the standalone sweep

    # The standalone sweep then catches what the per-topic prune left behind.
    swept = prune_stale_source_posts(db_session, as_of=NOW)
    assert swept == 1
    assert db_session.get(SourcePost, stale_b_id) is None
