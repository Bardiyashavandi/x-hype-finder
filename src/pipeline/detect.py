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

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

from src.models.topic import Topic

# Spike threshold: current filtered activity ≥ 3x the trailing baseline mean
# (FR-004, contracts/pipeline-stages.md § Detect).
SPIKE_THRESHOLD = 3.0

# Trailing window the baseline mean is computed over — matches the 7-day
# observation period new topics serve before Detect evaluates them at all
# (quickstart.md Scenario 1 seeds "TopicBaselineSnapshot rows for the
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
    window_start = as_of - timedelta(days=window_days)
    relevant = [
        snapshot.filtered_post_count
        for snapshot in snapshots
        if window_start <= snapshot.window_date < as_of
    ]
    if not relevant:
        return None
    return sum(relevant) / len(relevant)


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
    """
    if topic.observation_period_active:
        return DetectResult(is_spike=False, spike_ratio=None)

    as_of = as_of if as_of is not None else date.today()
    baseline_mean = compute_baseline_mean(baseline_snapshots, as_of=as_of)

    if baseline_mean is None:
        # No baseline history in the trailing window to compare against —
        # conservative default: don't flag a spike without a real baseline.
        return DetectResult(is_spike=False, spike_ratio=None)

    if baseline_mean == 0:
        # Zero historical activity: any current activity is an infinite
        # ratio by definition, which trivially clears the 3x threshold.
        is_spike = current_filtered_count > 0
        return DetectResult(is_spike=is_spike, spike_ratio=float("inf") if is_spike else 0.0)

    spike_ratio = current_filtered_count / baseline_mean
    return DetectResult(is_spike=spike_ratio >= SPIKE_THRESHOLD, spike_ratio=spike_ratio)
