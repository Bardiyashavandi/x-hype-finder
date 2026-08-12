"""Unit tests for the Relevance Filter (src/pipeline/relevance_filter.py,
contracts/pipeline-stages.md § Relevance Filter, data-model.md §
RelevantPost).
"""

from datetime import UTC, datetime

from src.pipeline.fetch import AuthorMetadata, RawPost
from src.pipeline.relevance_filter import RelevanceOutcome, filter_relevance

NOW = datetime(2026, 8, 12, tzinfo=UTC)


def _post(post_id: str, text: str) -> RawPost:
    return RawPost(
        x_post_id=post_id,
        author_handle=f"user_{post_id}",
        text=text,
        posted_at=NOW,
        author_metadata=AuthorMetadata(
            account_age_days=500, followers_count=100, following_count=50, post_frequency=1.0
        ),
    )


def test_post_with_no_exclude_term_match_is_kept():
    posts = [_post("1", "can't find a sublet anywhere in this city")]

    results = filter_relevance(posts, ["sublet.com"])

    assert results[0].relevance_outcome == RelevanceOutcome.KEPT
    assert results[0].matched_term is None


def test_post_matching_exclude_term_is_tagged_excluded_with_matched_term():
    posts = [_post("1", "just use sublet.com, problem solved")]

    results = filter_relevance(posts, ["sublet.com"])

    assert results[0].relevance_outcome == RelevanceOutcome.EXCLUDED_TERM_MATCH
    assert results[0].matched_term == "sublet.com"


def test_match_is_case_insensitive():
    posts = [_post("1", "Try SUBLET.COM instead")]

    results = filter_relevance(posts, ["sublet.com"])

    assert results[0].relevance_outcome == RelevanceOutcome.EXCLUDED_TERM_MATCH


def test_first_matching_term_wins_and_is_recorded():
    posts = [_post("1", "sublet.com and roomgone are both spam")]

    results = filter_relevance(posts, ["sublet.com", "roomgone"])

    assert results[0].matched_term == "sublet.com"


def test_no_post_is_dropped_from_the_record():
    """Every post gets a recorded relevance_outcome, mirroring
    FilterOutcome's 'every post gets an outcome' principle — even the
    excluded ones stay in the returned list rather than being dropped."""
    posts = [_post("1", "genuine complaint"), _post("2", "sublet.com spam")]

    results = filter_relevance(posts, ["sublet.com"])

    assert len(results) == len(posts)
    assert {r.post.x_post_id for r in results} == {"1", "2"}


def test_empty_exclude_terms_keeps_every_post():
    posts = [_post("1", "anything goes here")]

    results = filter_relevance(posts, [])

    assert results[0].relevance_outcome == RelevanceOutcome.KEPT
    assert results[0].matched_term is None


def test_links_are_stripped_before_matching_like_filter_pys_normalize():
    posts = [_post("1", "check this out https://sublet.com/listing/123")]

    results = filter_relevance(posts, ["sublet.com"])

    # The exclude term itself still matches mid-URL text normalization aside
    # — this locks in that _normalize strips links from the *post* text, not
    # that a link magically avoids exclusion.
    assert results[0].relevance_outcome == RelevanceOutcome.KEPT
