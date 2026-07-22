"""Digest model (tasks.md T011, data-model.md § Digest).

A ranked collection of Themes produced by one run — scheduled or on-demand
(FR-009). `status` transitioning to completed/partial/failed drives the
FR-023 notification (see src/notify/email.py, a later phase).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


class DigestRunType(enum.StrEnum):
    SCHEDULED = "scheduled"
    ON_DEMAND = "on_demand"


class DigestStatus(enum.StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class Digest(Base):
    __tablename__ = "digests"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    run_type: Mapped[DigestRunType] = mapped_column(Enum(DigestRunType), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[DigestStatus] = mapped_column(Enum(DigestStatus), nullable=False)
    notification_sent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
