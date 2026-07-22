"""TopicBaselineSnapshot write + inline per-run SourcePost retention prune
(tasks.md T042, FR-020, data-model.md § TopicBaselineSnapshot/SourcePost).

`write_baseline_snapshot` records today's filtered-post count for a topic —
the durable aggregate baseline history Detect reads (data-model.md); it
outlives the raw `SourcePost` rows. `prune_source_posts_for_topic` is the
per-run half of retention: it runs immediately after each run writes that
topic's baseline snapshot, deleting `SourcePost` rows older than the
drill-down window. T070 (Polish) separately covers a standalone periodic
sweep for rows this per-run prune could miss (e.g. from a run that failed
before completing its prune step) — distinction clarified per
/speckit-analyze finding D1.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from src.models.source_post import SourcePost
from src.models.topic_baseline_snapshot import TopicBaselineSnapshot

# FR-020: raw SourcePost rows are retained only long enough to serve
# drill-down for the digest they belong to (data-model.md, e.g. 30 days).
RETENTION_WINDOW = timedelta(days=30)


def write_baseline_snapshot(
    session: Session,
    topic_id: UUID,
    filtered_post_count: int,
    *,
    window_date: date | None = None,
) -> TopicBaselineSnapshot:
    """Upsert today's `(topic_id, window_date)` baseline row.

    Exactly one row per `(topic_id, window_date)` (data-model.md's uniqueness
    constraint) — a second run on the same day (e.g. an on-demand run after a
    scheduled one already ran) overwrites the count rather than duplicating
    the row.
    """
    effective_date = window_date if window_date is not None else datetime.now(UTC).date()

    existing = session.execute(
        select(TopicBaselineSnapshot).where(
            TopicBaselineSnapshot.topic_id == topic_id,
            TopicBaselineSnapshot.window_date == effective_date,
        )
    ).scalar_one_or_none()

    if existing is not None:
        existing.filtered_post_count = filtered_post_count
        return existing

    snapshot = TopicBaselineSnapshot(
        topic_id=topic_id,
        window_date=effective_date,
        filtered_post_count=filtered_post_count,
    )
    session.add(snapshot)
    return snapshot


def prune_source_posts_for_topic(
    session: Session,
    topic_id: UUID,
    *,
    as_of: datetime | None = None,
    retention_window: timedelta = RETENTION_WINDOW,
) -> int:
    """Delete this topic's `SourcePost` rows older than the retention window.

    Run immediately after this topic's baseline snapshot is written each run
    (FR-020) — by that point the aggregate baseline has already durably
    recorded this data's contribution, so the raw rows no longer need to
    survive. Returns the number of rows deleted.
    """
    effective_as_of = as_of if as_of is not None else datetime.now(UTC)
    cutoff = effective_as_of - retention_window

    result = session.execute(
        delete(SourcePost).where(
            SourcePost.topic_id == topic_id,
            SourcePost.posted_at < cutoff,
        )
    )
    return result.rowcount or 0
