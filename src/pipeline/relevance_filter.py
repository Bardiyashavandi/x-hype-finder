"""Relevance Filter: deterministic exclude-terms post-fetch filtering
(tasks.md T011, contracts/pipeline-stages.md § Relevance Filter,
data-model.md § RelevantPost, research.md §3).

Fully deterministic (Constitution Principle I) — no LLM/agent judgment. Runs
after Fetch and before the bot/noise Filter (`src/pipeline/filter.py`,
unchanged) and Signal Strength, catching anything the query-level `-"term"`
exclusion (`src/pipeline/idea_query_builder.py`) missed — e.g. a term
appearing mid-word, or X's search returning a near-match. No post is dropped
from the record — every post gets a `relevance_outcome`, mirroring
`FilterOutcome`'s "every post gets an outcome" principle even though nothing
here is persisted to a table.
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass

from src.pipeline.fetch import RawPost

_URL_PATTERN = re.compile(r"https?://\S+")


class RelevanceOutcome(enum.StrEnum):
    KEPT = "kept"
    EXCLUDED_TERM_MATCH = "excluded_term_match"


@dataclass(frozen=True)
class RelevantPost:
    post: RawPost
    relevance_outcome: RelevanceOutcome
    matched_term: str | None


def _normalize(text: str) -> str:
    """Same link-stripping/lowercasing/whitespace-collapsing pattern as
    `src/pipeline/filter.py`'s `_normalize` (research.md §3) — reused here
    rather than imported, since Filter's own version is private to that
    module and each stage's normalization stays independently testable."""
    without_links = _URL_PATTERN.sub("", text)
    return " ".join(without_links.lower().split())


def filter_relevance(posts: list[RawPost], exclude_terms: list[str]) -> list[RelevantPost]:
    """Case-insensitive substring match of each exclude term against the
    post's normalized text. The first matching term wins and is recorded as
    `matched_term`; a post matching none of `exclude_terms` is `kept`.
    """
    normalized_terms = [(term, _normalize(term)) for term in exclude_terms]

    results: list[RelevantPost] = []
    for post in posts:
        normalized_text = _normalize(post.text)
        matched_term = next(
            (
                term
                for term, normalized_term in normalized_terms
                if normalized_term and normalized_term in normalized_text
            ),
            None,
        )
        outcome = (
            RelevanceOutcome.EXCLUDED_TERM_MATCH
            if matched_term is not None
            else RelevanceOutcome.KEPT
        )
        results.append(
            RelevantPost(post=post, relevance_outcome=outcome, matched_term=matched_term)
        )

    return results
