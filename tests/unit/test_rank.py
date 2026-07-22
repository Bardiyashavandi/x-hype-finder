"""Unit tests for Rank descending-significance ordering (tasks.md T027,
contracts/pipeline-stages.md § Rank; FR-008).

Rank is fully deterministic — a plain sort over spike_ratio × confidence
across all Themes in a run, annotating each with a 1-indexed `rank`.
"""

from dataclasses import dataclass

from src.pipeline.rank import rank_themes


@dataclass
class _Theme:
    name: str
    spike_ratio: float | None
    confidence_score: int
    rank: int = 0


def test_higher_significance_ranks_first():
    a = _Theme("low", spike_ratio=2.0, confidence_score=50)
    b = _Theme("high", spike_ratio=5.0, confidence_score=80)

    ordered = rank_themes([a, b])

    assert [t.name for t in ordered] == ["high", "low"]
    assert b.rank == 1
    assert a.rank == 2


def test_rank_is_1_indexed_and_contiguous():
    themes = [
        _Theme("a", spike_ratio=1.0, confidence_score=10),
        _Theme("b", spike_ratio=1.0, confidence_score=90),
        _Theme("c", spike_ratio=1.0, confidence_score=50),
    ]

    ordered = rank_themes(themes)

    assert [t.rank for t in ordered] == [1, 2, 3]
    assert [t.name for t in ordered] == ["b", "c", "a"]


def test_none_spike_ratio_treated_as_neutral_not_bottom():
    # No spike_ratio (observation period / no baseline) shouldn't crash on
    # `None * int`, and a high-confidence Theme without one can still
    # outrank a low-confidence spiking Theme.
    no_ratio = _Theme("observation", spike_ratio=None, confidence_score=90)
    weak_spike = _Theme("weak_spike", spike_ratio=1.5, confidence_score=20)

    ordered = rank_themes([weak_spike, no_ratio])

    assert ordered[0].name == "observation"
    assert ordered[0].rank == 1


def test_ties_broken_by_confidence_then_stable_input_order():
    first = _Theme("first", spike_ratio=2.0, confidence_score=50)
    second = _Theme("second", spike_ratio=2.0, confidence_score=50)

    ordered = rank_themes([first, second])

    assert [t.name for t in ordered] == ["first", "second"]


def test_infinite_spike_ratio_sorts_to_the_top():
    normal = _Theme("normal", spike_ratio=3.0, confidence_score=95)
    zero_baseline_spike = _Theme("zero_baseline", spike_ratio=float("inf"), confidence_score=40)

    ordered = rank_themes([normal, zero_baseline_spike])

    assert ordered[0].name == "zero_baseline"


def test_empty_input_returns_empty_list():
    assert rank_themes([]) == []


def test_single_theme_is_rank_one():
    only = _Theme("solo", spike_ratio=4.0, confidence_score=60)

    ordered = rank_themes([only])

    assert ordered == [only]
    assert only.rank == 1
