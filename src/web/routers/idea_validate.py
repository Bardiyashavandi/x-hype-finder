"""`GET /api/idea-validate`, `POST /api/idea-validate`,
`GET /api/idea-validate/jobs/{job_id}` (specs/003-web-dashboard/plan.md §0.B, §1).

Idea Validation Mode is deliberately stateless — no DB writes at all, by
design (specs/002-idea-validation-mode/research.md §1). `GET` therefore
returns static config for the run form (the default lookback window), never
run history — a `GET` returning "run history" would be architecturally
impossible without reversing that design decision (plan.md §0.B). `POST`
starts a run as a background job (it calls Claude and Fetch, so it can take
minutes, same as digest run) via `run_idea_validation_structured` — the
structured sibling of the CLI's `run_idea_validation` (src/cli/idea_validate.py)
that returns a `ValidationReadout` instead of pre-rendered text, so the
dashboard gets real JSON (verdict text, signal-strength numbers, a themes
array) rather than a text blob.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from src.cli.idea_validate import run_idea_validation_structured
from src.config import ConfigError, load_config
from src.models.user import User
from src.pipeline.fetch import DEFAULT_LOOKBACK
from src.pipeline.idea_query_builder import IdeaValidationQuery
from src.report.validation_readout import ValidationReadout
from src.web.deps import get_current_user
from src.web.jobs import JobStatus, registry
from src.web.schemas import (
    IdeaValidateDefaultsResponse,
    IdeaValidateJobStatusResponse,
    IdeaValidateRunRequest,
    JobAcceptedResponse,
    SignalStrengthResponse,
    ValidationReadoutResponse,
    ValidationThemeResponse,
)

router = APIRouter()

_JOB_KIND = "idea_validate_run"


def _readout_to_response(readout: ValidationReadout) -> ValidationReadoutResponse:
    signal = readout.signal_strength
    return ValidationReadoutResponse(
        phrases=readout.query.phrases,
        exclude_terms=readout.query.exclude_terms,
        generated_at=readout.generated_at,
        verdict=readout.verdict,
        fetch_error=readout.fetch_error,
        signal_strength=SignalStrengthResponse(
            total_relevant_count=signal.total_relevant_count,
            distinct_author_count=signal.distinct_author_count,
            most_recent_post_at=signal.most_recent_post_at,
            oldest_post_at=signal.oldest_post_at,
            posts_last_24h=signal.posts_last_24h,
            posts_last_7d=signal.posts_last_7d,
        ),
        themes=[
            ValidationThemeResponse(
                summary=t.summary,
                representative_ask=t.representative_ask,
                recurrence_signal=t.recurrence_signal,
                cluster_post_count=t.cluster_post_count,
                distinct_author_count=t.distinct_author_count,
                example_post_texts=t.example_post_texts,
            )
            for t in readout.themes
        ],
    )


@router.get("", response_model=IdeaValidateDefaultsResponse)
def get_idea_validate_defaults(
    _user: User = Depends(get_current_user),
) -> IdeaValidateDefaultsResponse:
    return IdeaValidateDefaultsResponse(
        default_lookback_hours=int(DEFAULT_LOOKBACK.total_seconds() // 3600)
    )


@router.post("", response_model=JobAcceptedResponse, status_code=202)
def start_idea_validate_run(
    payload: IdeaValidateRunRequest,
    background_tasks: BackgroundTasks,
    _user: User = Depends(get_current_user),
) -> JobAcceptedResponse:
    until = payload.until or datetime.now(UTC)
    since = payload.since or (until - DEFAULT_LOOKBACK)
    try:
        query = IdeaValidationQuery(
            phrases=payload.phrases, exclude_terms=payload.exclude_terms, since=since, until=until
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        config = load_config()
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    job = registry.create(kind=_JOB_KIND)
    background_tasks.add_task(
        registry.run,
        job,
        run_idea_validation_structured,
        query,
        anthropic_api_key=config.anthropic_api_key,
        claude_model=config.claude_model,
    )
    return JobAcceptedResponse(job_id=job.id)


@router.get("/jobs/{job_id}", response_model=IdeaValidateJobStatusResponse)
def get_idea_validate_job(
    job_id: uuid.UUID, _user: User = Depends(get_current_user)
) -> IdeaValidateJobStatusResponse:
    job = registry.get(job_id)
    if job is None or job.kind != _JOB_KIND:
        raise HTTPException(status_code=404, detail=f"No idea-validate job with id {job_id}.")
    readout_response = (
        _readout_to_response(job.result) if job.status == JobStatus.COMPLETED else None
    )
    return IdeaValidateJobStatusResponse(
        status=job.status.value, readout=readout_response, error=job.error
    )
