"""DigestTopicResult model (tasks.md T012, data-model.md § DigestTopicResult).

Per-topic outcome within one Digest run — the entity that lets a topic appear
in a digest even when it has nothing to show (FR-017, edge cases in spec.md).
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


class DigestTopicOutcome(enum.StrEnum):
    THEMES_PRESENT = "themes_present"
    NO_SIGNIFICANT_ACTIVITY = "no_significant_activity"
    ALL_FILTERED_AS_NOISE = "all_filtered_as_noise"
    FETCH_ERROR = "fetch_error"
    INCOMPLETE_RATE_LIMITED = "incomplete_rate_limited"


class DigestTopicResult(Base):
    __tablename__ = "digest_topic_results"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    digest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("digests.id"), nullable=False)
    topic_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("topics.id"), nullable=False)
    outcome: Mapped[DigestTopicOutcome] = mapped_column(Enum(DigestTopicOutcome), nullable=False)
    error_detail: Mapped[str | None] = mapped_column(String, nullable=True)
