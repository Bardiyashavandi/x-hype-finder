"""TopicBaselineSnapshot model (tasks.md T010, data-model.md § TopicBaselineSnapshot).

The system-maintained historical activity baseline referenced in FR-004/FR-020.
Aggregated counts only, not raw posts, so raw source data doesn't have to be
retained long-term. This table is the durable historical record; it outlives
the raw SourcePost rows (see src/models/source_post.py retention note).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


class TopicBaselineSnapshot(Base):
    __tablename__ = "topic_baseline_snapshots"
    __table_args__ = (
        # exactly one row per (topic_id, window_date) — data-model.md
        UniqueConstraint("topic_id", "window_date", name="uq_baseline_topic_window_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"), nullable=False)
    window_date: Mapped[date] = mapped_column(Date, nullable=False)
    filtered_post_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False)
