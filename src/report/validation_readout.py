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

from dataclasses import dataclass, replace
from datetime import datetime

from src.agent.validate_summarize import ValidationTheme
from src.pipeline.idea_query_builder import IdeaValidationQuery
from src.pipeline.signal_strength import SignalStrength

NO_SIGNAL_MESSAGE = "No meaningful signal found."


VERDICT_UNAVAILABLE_MESSAGE = "unavailable (executive-summary synthesis failed — see themes below)."


@dataclass(frozen=True)
class ValidationReadout:
    query: IdeaValidationQuery
    signal_strength: SignalStrength
    themes: list[ValidationTheme]
    generated_at: datetime
    # None in two distinct cases, rendered differently (see
    # render_validation_readout): the zero-signal case (no verdict makes
    # sense — NO_SIGNAL_MESSAGE already is the top-line verdict), and a
    # signal-present run where the synthesis call itself failed (rendered
    # as VERDICT_UNAVAILABLE_MESSAGE instead of silently vanishing).
    verdict: str | None = None
    # Set only when Fetch itself failed (src/cli/idea_validate.py) — the
    # already-formatted "Fetch error (<kind>): <detail>" message, rendered
    # ahead of everything else. `themes`/`signal_strength` are the empty-input
    # values in this case, same as the zero-signal path.
    fetch_error: str | None = None


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
    verdict: str | None = None,
    fetch_error: str | None = None,
) -> ValidationReadout:
    """Assemble the final readout. `themes` is ordered by `cluster_post_count`
    descending, ties broken by `distinct_author_count` then original input
    order (data-model.md § ValidationReadout). `verdict` is the caller's
    already-computed executive-summary text (or `None` in the zero-signal
    case, or when Validate Synthesize failed) — this function stays a plain
    deterministic assembler, same as before; it never calls Claude itself.
    `fetch_error` is set only on the Fetch-failure path (`themes`/
    `signal_strength` are the empty-input values there)."""
    ordered = [theme for _, theme in sorted(enumerate(themes), key=_theme_sort_key, reverse=True)]
    return ValidationReadout(
        query=query,
        signal_strength=signal_strength,
        themes=ordered,
        generated_at=now,
        verdict=verdict,
        fetch_error=fetch_error,
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


def _without_fetch_error(readout: ValidationReadout) -> ValidationReadout:
    return replace(readout, fetch_error=None)


def render_validation_readout(readout: ValidationReadout) -> str:
    """Render the full readout as plain text — never a blank output, even
    when no signal was found (spec.md §7): a zero-signal case
    (`total_relevant_count == 0` or `themes == []`) states that explicitly
    instead.

    On the signal-present path, `Verdict:` is printed first — above
    `Signal strength:` and `Themes (N):` — so a strategist reads the
    conclusion before drilling into supporting detail (spec.md §5.3, §7).
    """
    if readout.fetch_error is not None:
        # Fetch never even ran the rest of the pipeline — state the error up
        # front, followed by the same empty-input readout a zero-signal case
        # would produce, rather than a crash or blank output.
        rest = render_validation_readout(_without_fetch_error(readout))
        return f"{readout.fetch_error}\n\n{rest}"

    header = [
        "== Idea Validation Readout ==",
        f"generated_at: {readout.generated_at.isoformat()}",
        f"phrases: {', '.join(readout.query.phrases)}",
    ]
    if readout.query.exclude_terms:
        header.append(f"exclude_terms: {', '.join(readout.query.exclude_terms)}")

    if readout.signal_strength.total_relevant_count == 0 or not readout.themes:
        # No Verdict block here — NO_SIGNAL_MESSAGE already is the top-line
        # verdict; Validate Synthesize is never even called in this case
        # (src/cli/idea_validate.py), so readout.verdict is always None.
        return "\n".join(
            [*header, "", NO_SIGNAL_MESSAGE, "", _render_signal_strength(readout.signal_strength)]
        )

    verdict_text = readout.verdict if readout.verdict is not None else VERDICT_UNAVAILABLE_MESSAGE
    body = [
        *header,
        "",
        f"Verdict:\n  {verdict_text}",
        "",
        _render_signal_strength(readout.signal_strength),
        "",
        f"Themes ({len(readout.themes)}):",
    ]
    for i, theme in enumerate(readout.themes, start=1):
        body.append("")
        body.append(_render_theme(i, theme))
    return "\n".join(body)
