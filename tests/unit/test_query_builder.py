"""Unit tests for the shared advanced-search query builder
(src/pipeline/query_builder.py), used by both Fetch clients (fetch.py,
fetch_twitterapis_com.py).
"""

from datetime import UTC, datetime

from src.pipeline import fetch as fetch_module
from src.pipeline import fetch_twitterapis_com as twitterapis_com_module
from src.pipeline.query_builder import build_search_query

SINCE = datetime(2026, 7, 1, tzinfo=UTC)
UNTIL = datetime(2026, 7, 22, tzinfo=UTC)


def test_plain_topic_name_is_wrapped_in_quotes_for_exact_phrase_match():
    query = build_search_query("AI agents", [], SINCE, UNTIL)

    assert '"AI agents"' in query


def test_cashtag_topic_name_is_passed_bare_for_cashtag_operator_match():
    query = build_search_query("$SOL", [], SINCE, UNTIL)

    assert "$SOL" in query
    assert '"$SOL"' not in query


def test_cashtag_topic_name_does_not_leak_quotes_into_keyword_clause():
    query = build_search_query("$SOL", ["solana"], SINCE, UNTIL)

    assert query == (
        "($SOL OR from:solana) "
        f"since_time:{int(SINCE.timestamp())} until_time:{int(UNTIL.timestamp())}"
    )


def test_plain_topic_name_query_shape_unchanged():
    query = build_search_query("AAPL", ["cnbc"], SINCE, UNTIL)

    assert query == (
        '("AAPL" OR from:cnbc) '
        f"since_time:{int(SINCE.timestamp())} until_time:{int(UNTIL.timestamp())}"
    )


def test_handles_are_still_combined_with_or_and_at_sign_stripped():
    query = build_search_query("$SOL", ["@solana", "cz_binance"], SINCE, UNTIL)

    assert "from:solana" in query
    assert "from:cz_binance" in query
    assert "@" not in query


def test_both_fetch_clients_share_the_same_query_builder():
    assert fetch_module.build_search_query is build_search_query
    assert twitterapis_com_module.build_search_query is build_search_query
