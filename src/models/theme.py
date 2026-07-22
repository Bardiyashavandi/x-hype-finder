"""Theme model (tasks.md T014, data-model.md § Theme).

A cluster of related, filtered posts for a topic within one run. `rank` orders
Themes by descending significance within a Digest (FR-008).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


class Theme(Base):
    __tablename__ = "themes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    digest_topic_result_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("digest_topic_results.id"), nullable=False
    )
    summary: Mapped[str] = mapped_column(String, nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    confidence_score: Mapped[int] = mapped_column(Integer, nullable=False)  # 0-100
    is_spike: Mapped[bool] = mapped_column(Boolean, nullable=False)
    spike_ratio: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    cluster_post_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
