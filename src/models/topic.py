"""Topic model (tasks.md T009, data-model.md § Topic).

A tracked keyword/ticker belonging to one user (FR-001). `first_tracked_at`
anchors the 7-day observation window (FR-005) — see `observation_period_active`.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import Enum, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from src.db.session import Base

OBSERVATION_PERIOD = timedelta(days=7)


class TopicStatus(enum.StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


class Topic(Base):
    __tablename__ = "topics"
    __table_args__ = (
        # name required, non-empty, unique per user_id among ACTIVE topics only (data-model.md) —
        # a removed topic may share a name with a re-added active one; re-adding should reactivate
        # the original row (preserving topic_id-linked history) rather than insert a new one.
        Index(
            "uq_topic_user_name_active",
            "user_id",
            "name",
            unique=True,
            sqlite_where=text("status = 'active'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    x_handles: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[TopicStatus] = mapped_column(
        Enum(TopicStatus), default=TopicStatus.ACTIVE, nullable=False
    )
    first_tracked_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    @property
    def observation_period_active(self) -> bool:
        """Derived, not stored — True while Detect must not flag a spike (FR-005)."""
        first_tracked_at = self.first_tracked_at
        if first_tracked_at.tzinfo is None:
            first_tracked_at = first_tracked_at.replace(tzinfo=UTC)
        return datetime.now(UTC) - first_tracked_at < OBSERVATION_PERIOD
