"""Unit tests for Idea Validation's query construction
(src/pipeline/idea_query_builder.py, contracts/pipeline-stages.md § Query
Construction, data-model.md § IdeaValidationQuery).
"""

from datetime import UTC, datetime

import pytest

from src.pipeline.idea_query_builder import IdeaValidationQuery, build_idea_validation_query

SINCE = datetime(2026, 7, 1, tzinfo=UTC)
UNTIL = datetime(2026, 7, 22, tzinfo=UTC)


def test_phrases_are_or_quoted_together():
    query = build_idea_validation_query(
        ["can't find sublet", "no easy way to sublet"], [], SINCE, UNTIL
    )

    assert '"can\'t find sublet"' in query
    assert '"no easy way to sublet"' in query
    assert " OR " in query


def test_single_phrase_is_quoted():
    query = build_idea_validation_query(["sublet is a nightmare"], [], SINCE, UNTIL)

    assert '"sublet is a nightmare"' in query


def test_exclude_terms_appear_as_negated_clauses():
    query = build_idea_validation_query(["sublet is a nightmare"], ["sublet.com"], SINCE, UNTIL)

    assert '-"sublet.com"' in query


def test_multiple_exclude_terms_each_appear_as_negated_clauses():
    query = build_idea_validation_query(
        ["can't find sublet"], ["sublet.com", "roomgone"], SINCE, UNTIL
    )

    assert '-"sublet.com"' in query
    assert '-"roomgone"' in query


def test_no_exclude_terms_means_no_negated_clause():
    query = build_idea_validation_query(["can't find sublet"], [], SINCE, UNTIL)

    assert "-" not in query.split("since_time")[0].replace('"', "")


def test_empty_phrase_list_is_rejected():
    with pytest.raises(ValueError):
        build_idea_validation_query([], [], SINCE, UNTIL)


def test_query_includes_since_until_window():
    query = build_idea_validation_query(["can't find sublet"], [], SINCE, UNTIL)

    assert f"since_time:{int(SINCE.timestamp())}" in query
    assert f"until_time:{int(UNTIL.timestamp())}" in query


# --- IdeaValidationQuery dataclass ---


def test_idea_validation_query_strips_whitespace_and_drops_empty_phrases():
    query = IdeaValidationQuery(
        phrases=["  can't find sublet  ", "", "   "],
        exclude_terms=[],
        since=SINCE,
        until=UNTIL,
    )

    assert query.phrases == ["can't find sublet"]


def test_idea_validation_query_rejects_all_empty_phrases():
    with pytest.raises(ValueError):
        IdeaValidationQuery(phrases=["   ", ""], exclude_terms=[], since=SINCE, until=UNTIL)


def test_idea_validation_query_rejects_no_phrases_at_all():
    with pytest.raises(ValueError):
        IdeaValidationQuery(phrases=[], exclude_terms=[], since=SINCE, until=UNTIL)


def test_idea_validation_query_dedupes_phrases_case_insensitively():
    query = IdeaValidationQuery(
        phrases=["Can't Find Sublet", "can't find sublet"],
        exclude_terms=[],
        since=SINCE,
        until=UNTIL,
    )

    assert query.phrases == ["Can't Find Sublet"]


def test_idea_validation_query_dedupes_exclude_terms_case_insensitively():
    query = IdeaValidationQuery(
        phrases=["can't find sublet"],
        exclude_terms=["Sublet.com", "sublet.com"],
        since=SINCE,
        until=UNTIL,
    )

    assert query.exclude_terms == ["Sublet.com"]


def test_idea_validation_query_empty_exclude_terms_is_valid():
    query = IdeaValidationQuery(
        phrases=["can't find sublet"], exclude_terms=[], since=SINCE, until=UNTIL
    )

    assert query.exclude_terms == []
