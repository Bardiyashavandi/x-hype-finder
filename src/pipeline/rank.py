"""Rank: descending-significance ordering across a run's Themes (tasks.md T041,
contracts/pipeline-stages.md § Rank; FR-008).

Fully deterministic — no LLM/agent judgment (Constitution Principle I).
Input is every Theme produced across *all* of a user's topics in one run
(contracts/pipeline-stages.md: "all Themes produced for a user's run across
all their topics"), not just one topic's — the caller (orchestrator) collects
Themes from every topic before calling this once per run.
"""

from __future__ import annotations

from typing import Protocol, TypeVar


class RankableTheme(Protocol):
    spike_ratio: float | None
    confidence_score: int
    rank: int


ThemeT = TypeVar("ThemeT", bound=RankableTheme)


def _significance(theme: RankableTheme) -> float:
    """spike_ratio × confidence (contracts/pipeline-stages.md), with a neutral
    spike_ratio of 1.0 when none is set (observation period / no baseline
    yet) so such Themes still sort by confidence alone rather than sinking to
    the bottom or crashing on `None * int`."""
    spike_component = theme.spike_ratio if theme.spike_ratio is not None else 1.0
    return spike_component * theme.confidence_score


def rank_themes(themes: list[ThemeT]) -> list[ThemeT]:
    """Sort `themes` descending by significance and set `.rank` in place
    (1 = most significant). Ties broken by confidence_score, then by the
    original input order (stable sort) for reproducibility.

    Returns the newly-ordered list; `themes` itself is not reordered, but
    every element's `.rank` attribute is mutated as a side effect.
    """
    ordered = sorted(
        enumerate(themes),
        key=lambda pair: (_significance(pair[1]), pair[1].confidence_score, -pair[0]),
        reverse=True,
    )
    result = [theme for _, theme in ordered]
    for i, theme in enumerate(result):
        theme.rank = i + 1
    return result
