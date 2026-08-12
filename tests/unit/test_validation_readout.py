"""Unit tests for the Validation Readout assembler/renderer
(src/report/validation_readout.py) — specifically the `verdict` field added
for the top-level executive-summary synthesis step (spec.md §5.3, §7 of
specs/002-idea-validation-mode). Pure functions, no mocking needed.
"""

from datetime import UTC, datetime

from src.agent.validate_summarize import ValidationTheme
from src.pipeline.idea_query_builder import IdeaValidationQuery
from src.pipeline.signal_strength import SignalStrength
from src.report.validation_readout import (
    NO_SIGNAL_MESSAGE,
    VERDICT_UNAVAILABLE_MESSAGE,
    build_validation_readout,
    render_validation_readout,
)

NOW = datetime(2026, 8, 12, tzinfo=UTC)


def _query() -> IdeaValidationQuery:
    return IdeaValidationQuery(
        phrases=["can't find sublet"], exclude_terms=[], since=NOW, until=NOW
    )


def _theme(**overrides) -> ValidationTheme:
    defaults = dict(
        summary="People struggle to find short-term sublets.",
        representative_ask="I just need a place for a few months.",
        recurrence_signal="recurring",
        cluster_post_count=3,
        distinct_author_count=3,
        example_post_texts=["Can't find a sublet anywhere"],
    )
    defaults.update(overrides)
    return ValidationTheme(**defaults)


def _signal_strength(**overrides) -> SignalStrength:
    defaults = dict(
        total_relevant_count=3,
        distinct_author_count=3,
        most_recent_post_at=NOW,
        oldest_post_at=NOW,
        posts_last_24h=1,
        posts_last_7d=3,
    )
    defaults.update(overrides)
    return SignalStrength(**defaults)


def test_verdict_defaults_to_none_when_not_supplied():
    readout = build_validation_readout(_query(), _signal_strength(), [_theme()], now=NOW)

    assert readout.verdict is None


def test_verdict_is_carried_through_when_supplied():
    readout = build_validation_readout(
        _query(), _signal_strength(), [_theme()], now=NOW, verdict="A real, validated problem."
    )

    assert readout.verdict == "A real, validated problem."


def test_verdict_block_appears_before_signal_strength_and_themes():
    readout = build_validation_readout(
        _query(), _signal_strength(), [_theme()], now=NOW, verdict="A real, validated problem."
    )

    rendered = render_validation_readout(readout)

    assert "Verdict:" in rendered
    assert "A real, validated problem." in rendered
    verdict_index = rendered.index("Verdict:")
    signal_index = rendered.index("Signal strength:")
    themes_index = rendered.index("Themes (")
    assert verdict_index < signal_index < themes_index


def test_none_verdict_on_signal_present_path_renders_unavailable_fallback():
    """A signal-present run where Validate Synthesize itself failed must
    still render a Verdict section — never silently vanish — with the
    explicit unavailable message instead of the real verdict text."""
    readout = build_validation_readout(
        _query(), _signal_strength(), [_theme()], now=NOW, verdict=None
    )

    rendered = render_validation_readout(readout)

    assert "Verdict:" in rendered
    assert VERDICT_UNAVAILABLE_MESSAGE in rendered


def test_zero_signal_case_has_no_verdict_block_at_all():
    """NO_SIGNAL_MESSAGE is already the top-line verdict in this case —
    Validate Synthesize is never called (src/cli/idea_validate.py), so no
    Verdict block (real or fallback) should appear."""
    readout = build_validation_readout(
        _query(), _signal_strength(total_relevant_count=0), [], now=NOW, verdict=None
    )

    rendered = render_validation_readout(readout)

    assert NO_SIGNAL_MESSAGE in rendered
    assert "Verdict:" not in rendered
    assert VERDICT_UNAVAILABLE_MESSAGE not in rendered
