"""X/Twitter advanced-search query construction shared by both Fetch providers
(src/pipeline/fetch.py and src/pipeline/fetch_twitterapis_com.py).
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime


def build_search_query(
    topic_name: str, x_handles: Iterable[str], since: datetime, until: datetime
) -> str:
    """Build the advanced-search query string for one topic's fetch window.

    A topic name starting with "$" is a cashtag: it's passed bare so the API's
    cashtag operator matches actual ticker mentions, instead of being quoted
    into an exact-phrase text search that also catches unrelated uses of the
    same word (e.g. "$SOL" quoted would literal-match "sol" meaning sun/ground
    in other languages).
    """
    topic_term = topic_name if topic_name.startswith("$") else f'"{topic_name}"'
    terms = [topic_term, *(f"from:{handle.lstrip('@')}" for handle in x_handles)]
    keyword_clause = " OR ".join(terms)
    since_ts, until_ts = int(since.timestamp()), int(until.timestamp())
    return f"({keyword_clause}) since_time:{since_ts} until_time:{until_ts}"
