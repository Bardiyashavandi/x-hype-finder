"""EvaluationLabel model — one shared table for every judgment-making stage's
human-in-the-loop evaluation (Filter, Detect, Cluster, Summarize, Draft Post,
Digest), rather than a separate table per stage.

`target_id` intentionally has no foreign key — it points at whichever model
`stage` judges (`SourcePost` for filter, `Theme` for detect/cluster/summarize,
`DraftPost` for draft, `Digest` for digest). A single column can't carry an FK
to four different tables, so this is a polymorphic association enforced only
at the application layer (src/cli/eval.py), not the database.

Detect and Cluster and Summarize all target `Theme` — there is no separate
"detect result" entity in this schema; the spike call (`is_spike`/
`spike_ratio`) and the cluster membership both live on `Theme` already, so
each stage just judges a different aspect of the same row.

`label_type` holds "correct"/"incorrect" for the three binary stages (Filter,
Detect, Cluster) or "1".."5" for the three rated stages (Summarize, Draft,
Digest) — one column for both since the schema is meant to stay a single
shared table (see BINARY_STAGES/RATED_STAGES below for which is which).

The unique constraint is `(stage, target_id, labeled_by_user_id)`, not just
`(stage, target_id)` — two different users may independently label the same
item (useful for inter-rater agreement); a single user just can't double
label the same item for the same stage.
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


class EvalStage(enum.StrEnum):
    FILTER = "filter"
    DETECT = "detect"
    CLUSTER = "cluster"
    SUMMARIZE = "summarize"
    DRAFT = "draft"
    DIGEST = "digest"


BINARY_STAGES = frozenset({EvalStage.FILTER, EvalStage.DETECT, EvalStage.CLUSTER})
RATED_STAGES = frozenset({EvalStage.SUMMARIZE, EvalStage.DRAFT, EvalStage.DIGEST})

CORRECT = "correct"
INCORRECT = "incorrect"
BINARY_LABEL_VALUES = frozenset({CORRECT, INCORRECT})
RATING_LABEL_VALUES = frozenset({"1", "2", "3", "4", "5"})


def valid_label_values(stage: EvalStage) -> frozenset[str]:
    """Legal `label_type` values for `stage` — binary stages accept
    correct/incorrect, rated stages accept 1-5."""
    return BINARY_LABEL_VALUES if stage in BINARY_STAGES else RATING_LABEL_VALUES


class EvaluationLabel(Base):
    __tablename__ = "evaluation_labels"
    __table_args__ = (
        UniqueConstraint(
            "stage", "target_id", "labeled_by_user_id", name="uq_eval_label_stage_target_labeler"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    stage: Mapped[EvalStage] = mapped_column(Enum(EvalStage), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    label_type: Mapped[str] = mapped_column(String, nullable=False)
    notes: Mapped[str | None] = mapped_column(String, nullable=True)
    labeled_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), nullable=False
    )
    labeled_by_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
