"""SourcePost model (tasks.md T013, data-model.md § SourcePost).

A single retrieved post for a topic, carrying its filter outcome and cluster
assignment. `is_example` flags the curated 3-5 posts shown by default per
Theme, distinct from the full drill-down set (FR-008, FR-016) —
added per /speckit-analyze finding I2.

Retention (FR-020): rows here are retained only long enough to serve
drill-down and to compute the day's TopicBaselineSnapshot count; see
src/pipeline/baseline.py (a later phase) for the prune job.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


class FilterOutcome(enum.StrEnum):
    KEPT = "kept"
    EXCLUDED_RULE = "excluded_rule"
    EXCLUDED_DEEPER_CHECK = "excluded_deeper_check"


class SourcePost(Base):
    __tablename__ = "source_posts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"), nullable=False)
    digest_topic_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("digest_topic_results.id"), nullable=False
    )
    x_post_id: Mapped[str] = mapped_column(String, nullable=False)
    author_handle: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    filter_outcome: Mapped[FilterOutcome] = mapped_column(Enum(FilterOutcome), nullable=False)
    theme_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("themes.id"), nullable=True)
    is_example: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
