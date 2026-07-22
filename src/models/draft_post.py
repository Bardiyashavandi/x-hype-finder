"""DraftPost model (tasks.md T015, data-model.md § DraftPost).

A system-generated post derived from a high-signal Theme, pending manual or
autonomous handling. See data-model.md's state machine (FR-010, FR-012,
FR-019): `status` is assigned exactly once at creation, based on the
PostingMode in effect at that moment, and never changed retroactively.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


class DraftPostStatus(enum.StrEnum):
    HELD_MANUAL = "held_manual"
    PUBLISHED_MANUAL = "published_manual"
    HELD_BELOW_THRESHOLD = "held_below_threshold"
    PUBLISHED_AUTO = "published_auto"
    PUBLISH_FAILED = "publish_failed"


class DraftPost(Base):
    __tablename__ = "draft_posts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    theme_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("themes.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    draft_text: Mapped[str] = mapped_column(String, nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-100
    status: Mapped[DraftPostStatus] = mapped_column(Enum(DraftPostStatus), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    publish_error: Mapped[str | None] = mapped_column(String, nullable=True)
