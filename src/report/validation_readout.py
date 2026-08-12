"""Validation Readout: assembles Signal Strength + Themes + query into the
final printable/writable output (tasks.md T014, contracts/pipeline-stages.md
§ Validation Readout, data-model.md § ValidationReadout).

Idea Validation mode's analogue of `Digest` — but a plain dataclass, never a
DB row (research.md §1). `render_validation_readout` always produces a
complete, non-blank readout, even in the zero-signal case (spec.md §7),
mirroring `DigestTopicOutcome`'s principle that a topic/query never silently
vanishes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.agent.validate_summarize import ValidationTheme
from src.pipeline.idea_query_builder import IdeaValidationQuery
from src.pipeline.signal_strength import SignalStrength

NO_SIGNAL_MESSAGE = "No meaningful signal found."


@dataclass(frozen=True)
class ValidationReadout:
    query: IdeaValidationQuery
    signal_strength: SignalStrength
    themes: list[ValidationTheme]
    generated_at: datetime


def _theme_sort_key(pair: tuple[int, ValidationTheme]) -> tuple[int, int, int]:
    index, theme = pair
    # Descending cluster_post_count, then descending distinct_author_count,
    # then original input order (stable) — the -index trick mirrors
    # src/pipeline/rank.py's rank_themes for a reverse=True sort.
    return (theme.cluster_post_count, theme.distinct_author_count, -index)


def build_validation_readout(
    query: IdeaValidationQuery,
    signal_strength: SignalStrength,
    themes: list[ValidationTheme],
    *,
    now: datetime,
) -> ValidationReadout:
    """Assemble the final readout. `themes` is ordered by `cluster_post_count`
    descending, ties broken by `distinct_author_count` then original input
    order (data-model.md § ValidationReadout)."""
    ordered = [theme for _, theme in sorted(enumerate(themes), key=_theme_sort_key, reverse=True)]
    return ValidationReadout(
        query=query, signal_strength=signal_strength, themes=ordered, generated_at=now
    )


def _render_signal_strength(signal_strength: SignalStrength) -> str:
    most_recent = (
        signal_strength.most_recent_post_at.isoformat()
        if signal_strength.most_recent_post_at is not None
        else "n/a"
    )
    oldest = (
        signal_strength.oldest_post_at.isoformat()
        if signal_strength.oldest_post_at is not None
        else "n/a"
    )
    return "\n".join(
        [
            "Signal strength:",
            f"  total_relevant_count: {signal_strength.total_relevant_count}",
            f"  distinct_author_count: {signal_strength.distinct_author_count}",
            f"  posts_last_24h: {signal_strength.posts_last_24h}",
            f"  posts_last_7d: {signal_strength.posts_last_7d}",
            f"  most_recent_post_at: {most_recent}",
            f"  oldest_post_at: {oldest}",
        ]
    )


def _render_theme(rank: int, theme: ValidationTheme) -> str:
    lines = [
        f"[{rank}] recurrence_signal={theme.recurrence_signal}  "
        f"cluster_post_count={theme.cluster_post_count}  "
        f"distinct_author_count={theme.distinct_author_count}",
        f"    summary: {theme.summary}",
        f"    representative_ask: {theme.representative_ask}",
        "    examples:",
    ]
    lines.extend(f"      - {text}" for text in theme.example_post_texts)
    return "\n".join(lines)


def render_validation_readout(readout: ValidationReadout) -> str:
    """Render the full readout as plain text — never a blank output, even
    when no signal was found (spec.md §7): a zero-signal case
    (`total_relevant_count == 0` or `themes == []`) states that explicitly
    instead."""
    header = [
        "== Idea Validation Readout ==",
        f"generated_at: {readout.generated_at.isoformat()}",
        f"phrases: {', '.join(readout.query.phrases)}",
    ]
    if readout.query.exclude_terms:
        header.append(f"exclude_terms: {', '.join(readout.query.exclude_terms)}")

    if readout.signal_strength.total_relevant_count == 0 or not readout.themes:
        return "\n".join(
            [*header, "", NO_SIGNAL_MESSAGE, "", _render_signal_strength(readout.signal_strength)]
        )

    body = [
        *header,
        "",
        _render_signal_strength(readout.signal_strength),
        "",
        f"Themes ({len(readout.themes)}):",
    ]
    for i, theme in enumerate(readout.themes, start=1):
        body.append("")
        body.append(_render_theme(i, theme))
    return "\n".join(body)
