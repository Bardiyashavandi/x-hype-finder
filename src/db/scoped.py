"""Per-user data isolation query helper (tasks.md T018, FR-015).

Every model in this system is owned by exactly one User, either directly (a
`user_id` column: Topic, Digest, DraftPost, PostingMode) or transitively
through its foreign-key chain up to a table that has one
(TopicBaselineSnapshot, DigestTopicResult, SourcePost, Theme). This module is
the single place that encodes each model's ownership path — no other module
should hand-write a raw, unscoped query against a user-owned table.
"""

from __future__ import annotations

import uuid
from typing import TypeVar

from sqlalchemy import Select, select

from src.models.digest import Digest
from src.models.digest_topic_result import DigestTopicResult
from src.models.draft_post import DraftPost
from src.models.evaluation_label import EvaluationLabel
from src.models.posting_mode import PostingMode
from src.models.source_post import SourcePost
from src.models.theme import Theme
from src.models.topic import Topic
from src.models.topic_baseline_snapshot import TopicBaselineSnapshot
from src.models.user import User

ModelT = TypeVar("ModelT")

_DIRECT_OWNERSHIP = (Topic, Digest, DraftPost, PostingMode)


def _scope_topic_baseline_snapshot(stmt: Select, user_id: uuid.UUID) -> Select:
    return stmt.join(Topic, TopicBaselineSnapshot.topic_id == Topic.id).where(
        Topic.user_id == user_id
    )


def _scope_digest_topic_result(stmt: Select, user_id: uuid.UUID) -> Select:
    return stmt.join(Digest, DigestTopicResult.digest_id == Digest.id).where(
        Digest.user_id == user_id
    )


def _scope_source_post(stmt: Select, user_id: uuid.UUID) -> Select:
    return stmt.join(Topic, SourcePost.topic_id == Topic.id).where(Topic.user_id == user_id)


def _scope_theme(stmt: Select, user_id: uuid.UUID) -> Select:
    return (
        stmt.join(DigestTopicResult, Theme.digest_topic_result_id == DigestTopicResult.id)
        .join(Digest, DigestTopicResult.digest_id == Digest.id)
        .where(Digest.user_id == user_id)
    )


_TRANSITIVE_SCOPES = {
    TopicBaselineSnapshot: _scope_topic_baseline_snapshot,
    DigestTopicResult: _scope_digest_topic_result,
    SourcePost: _scope_source_post,
    Theme: _scope_theme,
}


def scoped_select(model: type[ModelT], user_id: uuid.UUID) -> Select:
    """Return a SELECT for `model`, filtered to rows owned by `user_id` (FR-015).

    Raises ValueError for any model this module doesn't know how to scope —
    fail loudly rather than silently return an unfiltered, cross-user query.
    """
    stmt = select(model)

    if model is User:
        return stmt.where(User.id == user_id)

    if model is EvaluationLabel:
        # Owned by whoever labeled it, not by whoever owns the target row it
        # judges (EvaluationLabel.target_id has no FK — see its model docstring).
        return stmt.where(EvaluationLabel.labeled_by_user_id == user_id)

    if model in _DIRECT_OWNERSHIP:
        return stmt.where(model.user_id == user_id)

    scoper = _TRANSITIVE_SCOPES.get(model)
    if scoper is None:
        raise ValueError(
            f"{model.__name__} has no registered ownership scope in src/db/scoped.py — "
            "add one rather than querying it unscoped (FR-015)."
        )
    return scoper(stmt, user_id)
