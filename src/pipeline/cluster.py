"""Cluster: thematic grouping of filtered posts (tasks.md T039,
contracts/pipeline-stages.md § Cluster; FR-006, research.md §4).

Fully deterministic (Constitution Principle I) — groups a topic's `kept`
(post-Filter) posts into Theme candidates by embedding similarity, reusing
the same embedding provider abstraction (src/pipeline/embedding_provider.py)
Filter Tier 2 already uses. No LLM/agent judgment: grouping is a plain
similarity-threshold clustering over embedding vectors.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import AgglomerativeClustering

from src.pipeline.embedding_provider import get_embedding_provider
from src.pipeline.fetch import RawPost

# Posts with cosine similarity at/above this threshold land in the same
# Theme candidate group (research.md §4 — near-duplicate/related short
# posts; FR-006, User Story 1 Acceptance Scenario 4).
CLUSTER_SIMILARITY_THRESHOLD = 0.75


@dataclass(frozen=True)
class ThemeCandidate:
    posts: tuple[RawPost, ...]

    @property
    def post_count(self) -> int:
        return len(self.posts)


def _normalized_vectors(vectors: list[list[float]]) -> np.ndarray:
    array = np.asarray(vectors, dtype=float)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0  # avoid divide-by-zero for a degenerate all-zero embedding
    return array / norms


def cluster_posts(
    posts: list[RawPost],
    *,
    embed_fn: Callable[[list[str]], list[list[float]]] | None = None,
    similarity_threshold: float = CLUSTER_SIMILARITY_THRESHOLD,
) -> list[ThemeCandidate]:
    """Group kept posts into Theme candidates by embedding similarity.

    Every post lands in exactly one group — a post with no sufficiently
    similar peers becomes its own single-post group rather than being
    dropped (Cluster never excludes a post, only Filter does).
    """
    if not posts:
        return []
    if len(posts) == 1:
        return [ThemeCandidate(posts=(posts[0],))]

    resolved_embed_fn = embed_fn if embed_fn is not None else get_embedding_provider()
    vectors = resolved_embed_fn([post.text for post in posts])
    normalized = _normalized_vectors(vectors)
    distance_threshold = max(1.0 - similarity_threshold, 0.0)

    clustering = AgglomerativeClustering(
        n_clusters=None,
        distance_threshold=distance_threshold,
        metric="cosine",
        linkage="average",
    )
    labels = clustering.fit_predict(normalized)

    groups: dict[int, list[RawPost]] = {}
    for label, post in zip(labels, posts, strict=True):
        groups.setdefault(int(label), []).append(post)

    return [ThemeCandidate(posts=tuple(group)) for group in groups.values()]
