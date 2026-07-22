"""Unit tests for Cluster near-duplicate similarity grouping (tasks.md T026,
contracts/pipeline-stages.md § Cluster).

Uses an injected fake `embed_fn`, mirroring Filter Tier 2's test pattern
(tests/unit/test_filter_tier2.py) — Cluster's grouping logic is itself fully
deterministic (research.md §4); only the embedding *source* (Ollama) is
external, so no real Ollama call is needed to test it in isolation.
"""

from datetime import UTC, datetime

from src.pipeline.cluster import ThemeCandidate, cluster_posts
from src.pipeline.fetch import AuthorMetadata, RawPost

NOW = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)


def _post(post_id: str, text: str) -> RawPost:
    return RawPost(
        x_post_id=post_id,
        author_handle=f"user_{post_id}",
        text=text,
        posted_at=NOW,
        author_metadata=AuthorMetadata(
            account_age_days=400, followers_count=5000, following_count=500, post_frequency=5.0
        ),
    )


def _fixed_embed_fn(vectors: list[list[float]]):
    """Returns `vectors` verbatim regardless of input — order must match the
    `posts` list the test passes to `cluster_posts`."""

    def embed_fn(texts: list[str]) -> list[list[float]]:
        assert len(texts) == len(vectors)
        return vectors

    return embed_fn


def _post_ids(candidate: ThemeCandidate) -> set[str]:
    return {post.x_post_id for post in candidate.posts}


def test_empty_input_returns_no_groups():
    assert cluster_posts([], embed_fn=_fixed_embed_fn([])) == []


def test_single_post_becomes_its_own_group():
    posts = [_post("1", "Solo post about the topic")]

    groups = cluster_posts(posts, embed_fn=_fixed_embed_fn([[1.0, 0.0]]))

    assert len(groups) == 1
    assert groups[0].post_count == 1


def test_near_duplicate_posts_land_in_the_same_group():
    posts = [
        _post("1", "This ticker is about to explode, get in now"),
        _post("2", "This ticker is about to explode, get in right now"),
        _post("3", "This ticker is about to explode, get in soon"),
        _post("4", "Completely unrelated commentary about the weather today"),
    ]
    vectors = [
        [1.0, 0.0, 0.0],
        [0.99, 0.02, 0.0],
        [0.98, 0.03, 0.0],
        [0.0, 0.0, 1.0],
    ]

    groups = cluster_posts(posts, embed_fn=_fixed_embed_fn(vectors))

    assert len(groups) == 2
    groups_by_size = sorted(groups, key=lambda g: g.post_count)
    assert _post_ids(groups_by_size[0]) == {"4"}
    assert _post_ids(groups_by_size[1]) == {"1", "2", "3"}


def test_unrelated_posts_stay_in_separate_groups():
    posts = [_post("1", "Alpha"), _post("2", "Beta")]
    vectors = [[1.0, 0.0], [0.0, 1.0]]  # orthogonal — cosine similarity 0

    groups = cluster_posts(posts, embed_fn=_fixed_embed_fn(vectors))

    assert len(groups) == 2


def test_every_post_is_accounted_for_across_groups():
    posts = [_post(str(i), f"post number {i}") for i in range(6)]
    vectors = [
        [1.0, 0.0, 0.0],
        [0.99, 0.01, 0.0],
        [0.0, 1.0, 0.0],
        [0.01, 0.99, 0.0],
        [0.0, 0.0, 1.0],
        [0.0, 0.01, 0.99],
    ]

    groups = cluster_posts(posts, embed_fn=_fixed_embed_fn(vectors))

    all_ids: set[str] = set()
    for group in groups:
        all_ids |= _post_ids(group)
    assert all_ids == {str(i) for i in range(6)}


def test_similarity_threshold_is_configurable():
    posts = [_post("1", "Alpha"), _post("2", "Beta")]
    vectors = [[1.0, 0.0], [0.8, 0.6]]  # cosine similarity 0.8

    strict = cluster_posts(posts, embed_fn=_fixed_embed_fn(vectors), similarity_threshold=0.9)
    loose = cluster_posts(posts, embed_fn=_fixed_embed_fn(vectors), similarity_threshold=0.5)

    assert len(strict) == 2
    assert len(loose) == 1
