"""Unit tests for Detect baseline/spike math and the 7-day observation gate
(tasks.md T025, contracts/pipeline-stages.md § Detect).

Detect compares a topic's own filtered current activity against that same
topic's own filtered historical baseline only — never another topic's — and
must never flag a spike while the topic is inside its 7-day observation
period, regardless of activity level (FR-004, FR-005).
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from src.models.topic import Topic
from src.pipeline.detect import (
    BASELINE_WINDOW_DAYS,
    SPIKE_THRESHOLD,
    DetectResult,
    compute_baseline_mean,
    detect_spike,
)

TODAY = date(2026, 7, 22)


@dataclass(frozen=True)
class _Snapshot:
    window_date: date
    filtered_post_count: int


def _snapshots(counts: list[int], *, ending: date = TODAY) -> list[_Snapshot]:
    """One snapshot per day for len(counts) days immediately before `ending`."""
    return [
        _Snapshot(window_date=ending - timedelta(days=len(counts) - i), filtered_post_count=count)
        for i, count in enumerate(counts)
    ]


def _topic(*, first_tracked_days_ago: int) -> Topic:
    return Topic(first_tracked_at=datetime.now(UTC) - timedelta(days=first_tracked_days_ago))


def test_baseline_mean_averages_trailing_window_excluding_as_of_day():
    snapshots = _snapshots([10, 20, 30])  # 3 days ending the day before TODAY
    assert compute_baseline_mean(snapshots, as_of=TODAY) == 20.0


def test_baseline_mean_excludes_snapshot_on_as_of_date_itself():
    snapshots = [*_snapshots([10, 20]), _Snapshot(window_date=TODAY, filtered_post_count=999)]
    assert compute_baseline_mean(snapshots, as_of=TODAY) == 15.0


def test_baseline_mean_excludes_snapshots_older_than_the_window():
    old = _Snapshot(
        window_date=TODAY - timedelta(days=BASELINE_WINDOW_DAYS + 5), filtered_post_count=1000
    )
    recent = _snapshots([10, 20])
    assert compute_baseline_mean([old, *recent], as_of=TODAY) == 15.0


def test_baseline_mean_is_none_with_no_snapshots_in_window():
    assert compute_baseline_mean([], as_of=TODAY) is None


def test_spike_flagged_at_exactly_3x_baseline():
    topic = _topic(first_tracked_days_ago=30)
    snapshots = _snapshots([10, 10, 10])  # baseline mean = 10
    result = detect_spike(topic, 30, snapshots, as_of=TODAY)
    assert result.is_spike is True
    assert result.spike_ratio == SPIKE_THRESHOLD


def test_spike_not_flagged_just_below_3x_baseline():
    topic = _topic(first_tracked_days_ago=30)
    snapshots = _snapshots([10, 10, 10])
    result = detect_spike(topic, 29, snapshots, as_of=TODAY)
    assert result.is_spike is False
    assert result.spike_ratio == 2.9


def test_normal_non_spiking_control_topic_is_never_a_false_positive():
    topic = _topic(first_tracked_days_ago=30)
    snapshots = _snapshots([12, 9, 11, 10, 8, 10, 10])  # baseline mean = 10
    result = detect_spike(topic, 11, snapshots, as_of=TODAY)
    assert result.is_spike is False


def test_observation_period_active_never_flags_spike_regardless_of_activity():
    topic = _topic(first_tracked_days_ago=3)  # inside the 7-day window
    snapshots = _snapshots([1, 1, 1])
    result = detect_spike(topic, 1000, snapshots, as_of=TODAY)
    assert result == DetectResult(is_spike=False, spike_ratio=None)


def test_observation_period_over_lets_detect_evaluate_normally():
    topic = _topic(first_tracked_days_ago=8)  # just past the 7-day boundary
    snapshots = _snapshots([10, 10, 10])
    result = detect_spike(topic, 30, snapshots, as_of=TODAY)
    assert result.is_spike is True


def test_no_baseline_data_conservatively_does_not_flag_a_spike():
    topic = _topic(first_tracked_days_ago=30)
    result = detect_spike(topic, 500, [], as_of=TODAY)
    assert result == DetectResult(is_spike=False, spike_ratio=None)


def test_zero_baseline_with_any_current_activity_is_a_spike():
    topic = _topic(first_tracked_days_ago=30)
    snapshots = _snapshots([0, 0, 0])
    result = detect_spike(topic, 5, snapshots, as_of=TODAY)
    assert result.is_spike is True
    assert result.spike_ratio == float("inf")


def test_zero_baseline_with_zero_current_activity_is_not_a_spike():
    topic = _topic(first_tracked_days_ago=30)
    snapshots = _snapshots([0, 0, 0])
    result = detect_spike(topic, 0, snapshots, as_of=TODAY)
    assert result.is_spike is False
    assert result.spike_ratio == 0.0
