"""Unit tests for Filter Tier 2 embedding-based coordinated-content escalation
(tasks.md T024).

Uses an injected fake `embed_fn` — Tier 2's escalation logic is itself fully
deterministic (research.md §5); only the embedding *source* (Ollama) is
external, so no real Ollama call is needed to test it in isolation.
"""

from datetime import UTC, datetime

from src.models.source_post import FilterOutcome
from src.pipeline.fetch import AuthorMetadata, RawPost
from src.pipeline.filter import Tier1Decision, Tier1Result, apply_tier2, filter_posts

NOW = datetime(2026, 7, 22, 12, 0, 0, tzinfo=UTC)


def _post(post_id: str, author: str, text: str) -> RawPost:
    return RawPost(
        x_post_id=post_id,
        author_handle=author,
        text=text,
        posted_at=NOW,
        author_metadata=AuthorMetadata(
            account_age_days=400,
            followers_count=5000,
            following_count=500,
            post_frequency=5.0,
        ),
    )


def _fixed_embed_fn(vectors: list[list[float]]):
    """Returns `vectors` verbatim regardless of input — order must match the
    `all_posts` list the test passes to `apply_tier2`/`filter_posts`."""

    def embed_fn(texts: list[str]) -> list[list[float]]:
        assert len(texts) == len(vectors)
        return vectors

    return embed_fn


def _poison_embed_fn(texts: list[str]) -> list[list[float]]:
    raise AssertionError("embed_fn should not be called when there are no ambiguous posts")


def test_near_duplicate_content_from_distinct_authors_is_coordinated():
    alice = _post("1", "alice", "This ticker is about to explode, get in now")
    bob = _post("2", "bob", "This ticker is about to explode, get in now")
    dave = _post("3", "dave", "This ticker is about to explode, get in now")
    carol = _post("4", "carol", "Something entirely unrelated to any of this")

    all_posts = [alice, bob, dave, carol]
    tier1_results = {
        "1": Tier1Result(score=30.0, decision=Tier1Decision.AMBIGUOUS, reasons=()),
        "2": Tier1Result(score=30.0, decision=Tier1Decision.AMBIGUOUS, reasons=()),
        "3": Tier1Result(score=30.0, decision=Tier1Decision.AMBIGUOUS, reasons=()),
        "4": Tier1Result(score=0.0, decision=Tier1Decision.CLEAR_KEEP, reasons=()),
    }
    vectors = [
        [1.0, 0.0, 0.0],
        [0.99, 0.01, 0.0],
        [0.98, 0.02, 0.0],
        [0.0, 1.0, 0.0],
    ]

    outcomes = apply_tier2(
        [alice, bob, dave], all_posts, tier1_results, embed_fn=_fixed_embed_fn(vectors)
    )

    assert outcomes["1"] == FilterOutcome.EXCLUDED_DEEPER_CHECK
    assert outcomes["2"] == FilterOutcome.EXCLUDED_DEEPER_CHECK
    assert outcomes["3"] == FilterOutcome.EXCLUDED_DEEPER_CHECK


def test_single_similar_author_alone_is_not_enough_to_flag_coordinated():
    # Only one other distinct-author match — below COORDINATED_MIN_DISTINCT_AUTHORS (2) —
    # and a low Tier 1 score, so it should fall through the composite threshold to kept.
    alice = _post("1", "alice", "Interesting news about this ticker")
    bob = _post("2", "bob", "Interesting news about this ticker")

    all_posts = [alice, bob]
    tier1_results = {
        "1": Tier1Result(score=30.0, decision=Tier1Decision.AMBIGUOUS, reasons=()),
        "2": Tier1Result(score=0.0, decision=Tier1Decision.CLEAR_KEEP, reasons=()),
    }
    vectors = [[1.0, 0.0, 0.0], [0.99, 0.01, 0.0]]

    outcomes = apply_tier2([alice], all_posts, tier1_results, embed_fn=_fixed_embed_fn(vectors))

    assert outcomes["1"] == FilterOutcome.KEPT


def test_no_coordination_but_high_composite_score_is_excluded():
    lone = _post("1", "eve", "Ambiguous post with no matching content nearby")
    all_posts = [lone]
    tier1_results = {"1": Tier1Result(score=60.0, decision=Tier1Decision.AMBIGUOUS, reasons=())}
    vectors = [[1.0, 0.0, 0.0]]

    outcomes = apply_tier2([lone], all_posts, tier1_results, embed_fn=_fixed_embed_fn(vectors))

    assert outcomes["1"] == FilterOutcome.EXCLUDED_DEEPER_CHECK


def test_no_coordination_and_low_composite_score_is_kept():
    lone = _post("1", "eve", "Ambiguous post with no matching content nearby")
    all_posts = [lone]
    tier1_results = {"1": Tier1Result(score=30.0, decision=Tier1Decision.AMBIGUOUS, reasons=())}
    vectors = [[1.0, 0.0, 0.0]]

    outcomes = apply_tier2([lone], all_posts, tier1_results, embed_fn=_fixed_embed_fn(vectors))

    assert outcomes["1"] == FilterOutcome.KEPT


def test_apply_tier2_is_a_noop_when_no_ambiguous_posts():
    assert apply_tier2([], [], {}, embed_fn=_poison_embed_fn) == {}


def test_filter_posts_skips_tier2_embedding_call_when_all_posts_are_clear():
    # A clean, established account's post should resolve entirely at Tier 1 —
    # filter_posts must not pay for an embedding call it doesn't need.
    posts = [_post("1", "author", "Genuinely interesting, unremarkable news update.")]

    filtered = filter_posts(posts, embed_fn=_poison_embed_fn)

    assert filtered[0].filter_outcome == FilterOutcome.KEPT
    assert filtered[0].tier1_decision == Tier1Decision.CLEAR_KEEP


def test_filter_posts_end_to_end_routes_ambiguous_posts_through_tier2():
    # Each post is new_account (20) + link_heavy (10) = 30 at Tier 1 — ambiguous,
    # not clear-exclude — and all three are near-duplicate content from distinct
    # authors, so Tier 2 should flag them as coordinated.
    alice = RawPost(
        x_post_id="1",
        author_handle="alice",
        text="http://x.example/promo",
        posted_at=NOW,
        author_metadata=AuthorMetadata(
            account_age_days=5, followers_count=5000, following_count=500, post_frequency=5.0
        ),
    )
    bob = RawPost(
        x_post_id="2",
        author_handle="bob",
        text="http://x.example/promo",
        posted_at=NOW,
        author_metadata=AuthorMetadata(
            account_age_days=5, followers_count=5000, following_count=500, post_frequency=5.0
        ),
    )
    dave = RawPost(
        x_post_id="3",
        author_handle="dave",
        text="http://x.example/promo",
        posted_at=NOW,
        author_metadata=AuthorMetadata(
            account_age_days=5, followers_count=5000, following_count=500, post_frequency=5.0
        ),
    )
    vectors = [[1.0, 0.0, 0.0], [0.99, 0.01, 0.0], [0.98, 0.02, 0.0]]

    filtered = filter_posts([alice, bob, dave], embed_fn=_fixed_embed_fn(vectors))

    outcomes = {f.post.x_post_id: f.filter_outcome for f in filtered}
    assert outcomes == {
        "1": FilterOutcome.EXCLUDED_DEEPER_CHECK,
        "2": FilterOutcome.EXCLUDED_DEEPER_CHECK,
        "3": FilterOutcome.EXCLUDED_DEEPER_CHECK,
    }
