"""Import every model so Base.metadata is fully populated on package import.

Required for Alembic autogenerate (T007/T017) and any create_all() call to see
the complete schema regardless of which individual model module was imported.
"""

from src.models.digest import Digest, DigestRunType, DigestStatus
from src.models.digest_topic_result import DigestTopicOutcome, DigestTopicResult
from src.models.draft_post import DraftPost, DraftPostStatus
from src.models.evaluation_label import EvalStage, EvaluationLabel
from src.models.posting_mode import PostingMode, PostingModeValue
from src.models.source_post import FilterOutcome, SourcePost
from src.models.theme import Theme
from src.models.topic import Topic, TopicStatus
from src.models.topic_baseline_snapshot import TopicBaselineSnapshot
from src.models.user import User

__all__ = [
    "User",
    "Topic",
    "TopicStatus",
    "TopicBaselineSnapshot",
    "Digest",
    "DigestRunType",
    "DigestStatus",
    "DigestTopicResult",
    "DigestTopicOutcome",
    "SourcePost",
    "FilterOutcome",
    "Theme",
    "DraftPost",
    "DraftPostStatus",
    "EvaluationLabel",
    "EvalStage",
    "PostingMode",
    "PostingModeValue",
]
