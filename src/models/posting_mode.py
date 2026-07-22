"""PostingMode model (tasks.md T016, data-model.md § PostingMode).

Per-user state governing draft handling (FR-011, FR-013, FR-022). Validation
gates (bio-label check, validation-period check, 24h/5-post cap, kill switch)
are enforced procedurally at the moment they matter — see src/posting/
(a later phase) — this model only holds the state those checks read/write.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


class PostingModeValue(enum.StrEnum):
    MANUAL = "manual"
    AUTONOMOUS = "autonomous"


class PostingMode(Base):
    __tablename__ = "posting_modes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)
    mode: Mapped[PostingModeValue] = mapped_column(
        Enum(PostingModeValue), default=PostingModeValue.MANUAL, nullable=False
    )
    confidence_threshold: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-100
    validation_period_ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    kill_switch_engaged: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_post_published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )
