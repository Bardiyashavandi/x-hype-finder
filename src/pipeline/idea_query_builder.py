"""Idea Validation query construction (tasks.md T004, contracts/pipeline-stages.md
§ Query Construction, data-model.md § IdeaValidationQuery, research.md §3).

Fully deterministic (Constitution Principle I) — no LLM/agent judgment. Builds
one X advanced-search query string OR-ing every problem-describing phrase
together (quoted exact-phrase, same convention as `build_search_query` in
`src/pipeline/query_builder.py`), with exclude terms folded in as negated
`-"term"` clauses. This is a cost-reduction pass on Fetch volume, not the
sole relevance guarantee — the same `exclude_terms` list is re-checked
post-fetch against actual post text by `src/pipeline/relevance_filter.py`
(research.md §3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


def _dedupe_case_insensitive(values: list[str]) -> list[str]:
    """Preserve first-seen casing/order, drop later case-insensitive repeats
    — avoids an inflated/broken OR clause from e.g. "Sublet.com" and
    "sublet.com" both appearing (data-model.md § IdeaValidationQuery)."""
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


@dataclass(frozen=True)
class IdeaValidationQuery:
    """The CLI input, parsed once at the start of a run (data-model.md).

    `phrases` must be non-empty after stripping whitespace from each entry
    (same `.strip()` pattern as `Topic.name` in `src/cli/topic.py`) — at
    least one is required. Both `phrases` and `exclude_terms` are
    de-duplicated case-insensitively after stripping.
    """

    phrases: list[str]
    exclude_terms: list[str]
    since: datetime
    until: datetime

    def __post_init__(self) -> None:
        stripped_phrases = [p.strip() for p in self.phrases if p.strip()]
        if not stripped_phrases:
            raise ValueError("IdeaValidationQuery requires at least one non-empty phrase.")
        object.__setattr__(self, "phrases", _dedupe_case_insensitive(stripped_phrases))

        stripped_excludes = [t.strip() for t in self.exclude_terms if t.strip()]
        object.__setattr__(self, "exclude_terms", _dedupe_case_insensitive(stripped_excludes))


def build_idea_validation_query(
    phrases: list[str], exclude_terms: list[str], since: datetime, until: datetime
) -> str:
    """Build the advanced-search query string for an Idea Validation run.

    Every phrase is OR'd together as an independently-quoted exact phrase;
    each exclude term is appended as a negated `-"term"` clause
    (contracts/pipeline-stages.md § Query Construction). Rejects an empty
    `phrases` list rather than building a query with no keyword clause at
    all.
    """
    if not phrases:
        raise ValueError("build_idea_validation_query requires at least one phrase.")

    phrase_clause = " OR ".join(f'"{phrase}"' for phrase in phrases)
    exclude_clause = "".join(f' -"{term}"' for term in exclude_terms)
    since_ts, until_ts = int(since.timestamp()), int(until.timestamp())
    return f"({phrase_clause}){exclude_clause} since_time:{since_ts} until_time:{until_ts}"
