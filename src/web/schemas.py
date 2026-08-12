"""Pydantic request/response models for the web dashboard API
(specs/003-web-dashboard/plan.md §1).

These are the JSON shapes the API speaks — never the ORM/domain objects
directly — built from the ORM rows or dataclasses the reused business-logic
functions already return. Nothing here re-derives a business rule; each
field is a straight passthrough (see each router for the translation).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    password: str


class AuthStatusResponse(BaseModel):
    authenticated: bool


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------


class TopicResponse(BaseModel):
    id: uuid.UUID
    name: str
    x_handles: list[str]
    status: str
    first_tracked_at: datetime
    in_observation_period: bool


class TopicCreateRequest(BaseModel):
    name: str
    handles: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


class DraftResponse(BaseModel):
    id: uuid.UUID
    theme_id: uuid.UUID
    draft_text: str
    confidence_score: int
    status: str
    created_at: datetime
    published_at: datetime | None
    publish_error: str | None
    tweet_id: str | None
    tweet_url: str | None


class DraftPublishRequest(BaseModel):
    # Required literal `true` — mirrors the CLI's explicit `--yes`/interactive
    # confirmation (plan.md §1's endpoint table): a button click alone isn't
    # confirmation, the request body itself must assert it.
    confirmed: Literal[True]


# ---------------------------------------------------------------------------
# Eval
# ---------------------------------------------------------------------------


class EvalStageReport(BaseModel):
    kind: Literal["binary", "rating"]
    correct: int | None = None
    total: int | None = None
    avg: float | None = None
    n: int | None = None


class EvalReportResponse(BaseModel):
    report: dict[str, EvalStageReport | None]


# ---------------------------------------------------------------------------
# Digests
# ---------------------------------------------------------------------------


class DigestSummaryResponse(BaseModel):
    id: uuid.UUID
    run_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None


class SourcePostResponse(BaseModel):
    id: uuid.UUID
    author_handle: str
    text: str
    posted_at: datetime
    filter_outcome: str
    is_example: bool


class ThemeResponse(BaseModel):
    id: uuid.UUID
    rank: int
    confidence_score: int
    is_spike: bool
    spike_ratio: float | None
    cluster_post_count: int
    summary: str
    rationale: str
    # Curated 3-5 example posts (FR-008) — always populated.
    example_posts: list[SourcePostResponse]
    # Every post clustered into this Theme, including non-example ones —
    # populated only when `?full=true` (FR-016).
    source_posts: list[SourcePostResponse] | None = None


class DigestTopicResultResponse(BaseModel):
    topic_id: uuid.UUID
    topic_name: str
    outcome: str
    error_detail: str | None
    themes: list[ThemeResponse]
    # Themes hidden by CONFIDENCE_DISPLAY_THRESHOLD in the default (non-full)
    # view — 0 whenever `full=true` (nothing is hidden there).
    hidden_theme_count: int
    # Posts Filter excluded, or that Cluster left out of every Theme, for
    # this topic — populated only when `?full=true` (FR-016).
    excluded_posts: list[SourcePostResponse] | None = None


class DigestDetailResponse(BaseModel):
    id: uuid.UUID
    status: str
    run_type: str
    started_at: datetime
    completed_at: datetime | None
    topics: list[DigestTopicResultResponse]


class DigestRunRequest(BaseModel):
    topic_name: str | None = None


class JobAcceptedResponse(BaseModel):
    job_id: uuid.UUID


class DigestJobStatusResponse(BaseModel):
    status: str
    digest_id: uuid.UUID | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# Idea Validation
# ---------------------------------------------------------------------------


class IdeaValidateDefaultsResponse(BaseModel):
    # Idea Validation is deliberately stateless (plan.md §0.B) — this is
    # static config for the run form, not run history.
    default_lookback_hours: int


class IdeaValidateRunRequest(BaseModel):
    phrases: list[str]
    exclude_terms: list[str] = Field(default_factory=list)
    since: datetime | None = None
    until: datetime | None = None


class SignalStrengthResponse(BaseModel):
    total_relevant_count: int
    distinct_author_count: int
    most_recent_post_at: datetime | None
    oldest_post_at: datetime | None
    posts_last_24h: int
    posts_last_7d: int


class ValidationThemeResponse(BaseModel):
    summary: str
    representative_ask: str
    recurrence_signal: str
    cluster_post_count: int
    distinct_author_count: int
    example_post_texts: list[str]


class ValidationReadoutResponse(BaseModel):
    phrases: list[str]
    exclude_terms: list[str]
    generated_at: datetime
    verdict: str | None
    fetch_error: str | None
    signal_strength: SignalStrengthResponse
    themes: list[ValidationThemeResponse]


class IdeaValidateJobStatusResponse(BaseModel):
    status: str
    readout: ValidationReadoutResponse | None = None
    error: str | None = None
