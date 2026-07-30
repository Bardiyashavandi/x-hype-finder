"""Detect: baseline comparison + 7-day observation gate (tasks.md T038,
contracts/pipeline-stages.md § Detect; FR-004, FR-005).

Fully deterministic (Constitution Principle I) — no LLM/agent judgment.
Compares one topic's *own* filtered current activity to that topic's own
filtered historical baseline (`TopicBaselineSnapshot` rows), never to another
topic's activity. `is_spike` is unconditionally `False` while
`Topic.observation_period_active` (first 7 days, FR-005), regardless of how
much activity occurred.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from src.models.topic import Topic

# A fixed multiple of the baseline mean (e.g. "3x") is mis-calibrated across
# volume regimes: for count data, variance scales with the mean (Poisson-
# like), so a flat ratio is too loose for low-volume topics (ordinary count
# noise clears it trivially) and too tight for high-volume ones (a real
# trend may never reach it). Instead, a spike is current activity clearing
# the trailing baseline mean by K_SIGMA *effective standard deviations*
# (`sigma_eff` in `detect_spike`) — a threshold that adapts to each topic's
# own volume/variance. K_SIGMA=2.5 is a starting point pending calibration
# against real topic history.
K_SIGMA = 2.5

# Floor on the effective standard deviation used in the spike threshold —
# guards low/zero-variance baselines (e.g. a topic flat at 0-1 posts/day)
# from flagging on trivial absolute noise.
MIN_SIGMA_FLOOR = 1.0

# Trailing window the baseline mean/stdev are computed over — matches the
# 7-day observation period new topics serve before Detect evaluates them at
# all (quickstart.md Scenario 1 seeds "TopicBaselineSnapshot rows for the
# trailing week"; data-model.md's "trailing N days").
BASELINE_WINDOW_DAYS = 7


class BaselineSnapshotLike(Protocol):
    """Structural shape of a `TopicBaselineSnapshot` row — lets Detect stay
    unit-testable without a DB session (matches Filter's RawPost pattern)."""

    window_date: date
    filtered_post_count: int


@dataclass(frozen=True)
class DetectResult:
    is_spike: bool
    spike_ratio: float | None


def _relevant_counts(
    snapshots: list[BaselineSnapshotLike],
    *,
    as_of: date,
    window_days: int,
) -> list[int]:
    """Filtered-post counts from snapshots strictly inside the trailing
    `window_days`-day window ending the day before `as_of` — the shared
    windowing logic behind both `compute_baseline_mean` and
    `compute_baseline_stdev`.
    """
    window_start = as_of - timedelta(days=window_days)
    return [
        snapshot.filtered_post_count
        for snapshot in snapshots
        if window_start <= snapshot.window_date < as_of
    ]


def compute_baseline_mean(
    snapshots: list[BaselineSnapshotLike],
    *,
    as_of: date,
    window_days: int = BASELINE_WINDOW_DAYS,
) -> float | None:
    """Rolling mean of `filtered_post_count` over the trailing `window_days`
    days, excluding `as_of` itself (the current run's own window per
    data-model.md § TopicBaselineSnapshot). `None` when there's no baseline
    data in that window at all — distinct from a baseline of zero activity.
    """
    relevant = _relevant_counts(snapshots, as_of=as_of, window_days=window_days)
    if not relevant:
        return None
    return sum(relevant) / len(relevant)


def compute_baseline_stdev(
    snapshots: list[BaselineSnapshotLike],
    *,
    as_of: date,
    window_days: int = BASELINE_WINDOW_DAYS,
) -> float | None:
    """Population stdev of `filtered_post_count` over the same trailing
    window as `compute_baseline_mean`. Population (not sample) stdev, so
    it stays well-defined even for a single-snapshot window. `None` when
    there's no baseline data in the window at all.
    """
    relevant = _relevant_counts(snapshots, as_of=as_of, window_days=window_days)
    if not relevant:
        return None
    return statistics.pstdev(relevant)


def detect_spike(
    topic: Topic,
    current_filtered_count: int,
    baseline_snapshots: list[BaselineSnapshotLike],
    *,
    as_of: date | None = None,
) -> DetectResult:
    """Compare `current_filtered_count` to `topic`'s own trailing baseline.

    Unconditionally not a spike during the topic's first 7 tracked days
    (FR-005) — raw activity is still available to show, just never flagged.

    A spike is current activity clearing the trailing baseline mean by
    `K_SIGMA` effective standard deviations, where the effective stdev is
    the largest of: the trailing window's own stdev, a Poisson noise floor
    (`sqrt(mean)`, since count-data variance scales with its mean), and
    `MIN_SIGMA_FLOOR` — this adapts the threshold to each topic's own
    volume/variance instead of applying one fixed ratio to every topic
    regardless of how noisy or quiet it normally is. `spike_ratio` is
    unchanged — still current ÷ baseline mean — since it remains in use
    downstream (Rank, Summarize) as a magnitude signal, independent of the
    is_spike decision boundary.
    """
    if topic.observation_period_active:
        return DetectResult(is_spike=False, spike_ratio=None)

    as_of = as_of if as_of is not None else date.today()
    baseline_mean = compute_baseline_mean(baseline_snapshots, as_of=as_of)

    if baseline_mean is None:
        # No baseline history in the trailing window to compare against —
        # conservative default: don't flag a spike without a real baseline.
        return DetectResult(is_spike=False, spike_ratio=None)

    baseline_stdev = compute_baseline_stdev(baseline_snapshots, as_of=as_of) or 0.0
    sigma_eff = max(baseline_stdev, math.sqrt(baseline_mean), MIN_SIGMA_FLOOR)
    is_spike = current_filtered_count >= baseline_mean + K_SIGMA * sigma_eff

    if baseline_mean == 0:
        # Zero historical activity: any current activity is an infinite
        # ratio by definition — spike_ratio reports that regardless of the
        # is_spike decision above, which is now governed by MIN_SIGMA_FLOOR.
        spike_ratio = float("inf") if current_filtered_count > 0 else 0.0
        return DetectResult(is_spike=is_spike, spike_ratio=spike_ratio)

    spike_ratio = current_filtered_count / baseline_mean
    return DetectResult(is_spike=is_spike, spike_ratio=spike_ratio)
