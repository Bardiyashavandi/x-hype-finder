"""`GET /api/digests`, `GET /api/digests/{id}?full=`, `POST /api/digests/run`,
`GET /api/digests/jobs/{job_id}` (specs/003-web-dashboard/plan.md §1).

The list/detail endpoints are direct queries (mirroring `digest show`'s own
`_digest_for_user` + direct-query pattern, src/cli/digest.py) built into
Pydantic models from the ORM rows; `CONFIDENCE_DISPLAY_THRESHOLD` is
imported from `src/cli/digest.py` rather than re-derived, so the
confidence-hiding rule can't drift between CLI and API. The run endpoint
starts `run_digest` (src/pipeline/orchestrator.py) as a background job — it
takes minutes, so it can't block the request (plan.md §1 "Background jobs").
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.cli.digest import (
    CONFIDENCE_DISPLAY_THRESHOLD,
    _active_topic_by_name,
    _active_topics,
    _digest_for_user,
)
from src.config import load_config
from src.db.scoped import scoped_select
from src.models.digest import Digest, DigestRunType
from src.models.digest_topic_result import DigestTopicOutcome, DigestTopicResult
from src.models.source_post import SourcePost
from src.models.theme import Theme
from src.models.topic import Topic
from src.models.user import User
from src.pipeline.orchestrator import run_digest
from src.web.deps import get_current_user, get_db, get_session_factory
from src.web.jobs import JobStatus, registry
from src.web.schemas import (
    DigestDetailResponse,
    DigestJobStatusResponse,
    DigestRunRequest,
    DigestSummaryResponse,
    DigestTopicResultResponse,
    JobAcceptedResponse,
    SourcePostResponse,
    ThemeResponse,
)

router = APIRouter()

_JOB_KIND = "digest_run"


def _source_post_response(post: SourcePost) -> SourcePostResponse:
    return SourcePostResponse(
        id=post.id,
        author_handle=post.author_handle,
        text=post.text,
        posted_at=post.posted_at,
        filter_outcome=post.filter_outcome.value,
        is_example=post.is_example,
    )


@router.get("", response_model=list[DigestSummaryResponse])
def get_digests(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> list[DigestSummaryResponse]:
    digests = (
        db.execute(scoped_select(Digest, user.id).order_by(Digest.started_at.desc()))
        .scalars()
        .all()
    )
    return [
        DigestSummaryResponse(
            id=d.id,
            run_type=d.run_type.value,
            status=d.status.value,
            started_at=d.started_at,
            completed_at=d.completed_at,
        )
        for d in digests
    ]


@router.get("/{digest_id}", response_model=DigestDetailResponse)
def get_digest_detail(
    digest_id: uuid.UUID,
    full: bool = Query(default=False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DigestDetailResponse:
    digest = _digest_for_user(db, user.id, digest_id)
    if digest is None:
        raise HTTPException(status_code=404, detail=f"No digest found with id {digest_id}.")

    dtr_rows = db.execute(
        select(DigestTopicResult, Topic)
        .join(Topic, DigestTopicResult.topic_id == Topic.id)
        .where(DigestTopicResult.digest_id == digest.id)
        .order_by(Topic.name)
    ).all()

    topics_out: list[DigestTopicResultResponse] = []
    for dtr, topic in dtr_rows:
        themes = (
            db.execute(
                select(Theme).where(Theme.digest_topic_result_id == dtr.id).order_by(Theme.rank)
            )
            .scalars()
            .all()
        )
        # Display-layer filter only, same as `digest show` without `--full`
        # (src/cli/digest.py's CONFIDENCE_DISPLAY_THRESHOLD docstring) — the
        # underlying Theme rows are untouched; `full=true` shows every one.
        displayed = (
            themes
            if full
            else [t for t in themes if t.confidence_score >= CONFIDENCE_DISPLAY_THRESHOLD]
        )
        hidden_theme_count = 0 if full else len(themes) - len(displayed)

        theme_responses = []
        for theme in displayed:
            examples = (
                db.execute(
                    select(SourcePost).where(SourcePost.theme_id == theme.id, SourcePost.is_example)
                )
                .scalars()
                .all()
            )
            source_posts = None
            if full:
                # FR-016: every post clustered into this Theme, not just the
                # curated examples.
                all_posts = (
                    db.execute(select(SourcePost).where(SourcePost.theme_id == theme.id))
                    .scalars()
                    .all()
                )
                source_posts = [_source_post_response(p) for p in all_posts]
            theme_responses.append(
                ThemeResponse(
                    id=theme.id,
                    rank=theme.rank,
                    confidence_score=theme.confidence_score,
                    is_spike=theme.is_spike,
                    spike_ratio=float(theme.spike_ratio) if theme.spike_ratio is not None else None,
                    cluster_post_count=theme.cluster_post_count,
                    summary=theme.summary,
                    rationale=theme.rationale,
                    example_posts=[_source_post_response(p) for p in examples],
                    source_posts=source_posts,
                )
            )

        excluded_posts = None
        if full:
            # FR-016: posts Filter excluded, or that Cluster left out of
            # every Theme, are still part of "the full source data" for this
            # topic — mirrors `_print_source_posts(..., exclude_clustered=...)`.
            query = select(SourcePost).where(SourcePost.digest_topic_result_id == dtr.id)
            if dtr.outcome == DigestTopicOutcome.THEMES_PRESENT:
                query = query.where(SourcePost.theme_id.is_(None))
            posts = db.execute(query).scalars().all()
            excluded_posts = [_source_post_response(p) for p in posts]

        topics_out.append(
            DigestTopicResultResponse(
                topic_id=topic.id,
                topic_name=topic.name,
                outcome=dtr.outcome.value,
                error_detail=dtr.error_detail,
                themes=theme_responses,
                hidden_theme_count=hidden_theme_count,
                excluded_posts=excluded_posts,
            )
        )

    return DigestDetailResponse(
        id=digest.id,
        status=digest.status.value,
        run_type=digest.run_type.value,
        started_at=digest.started_at,
        completed_at=digest.completed_at,
        topics=topics_out,
    )


def _run_digest_job(
    user_id: uuid.UUID,
    topic_name: str | None,
    session_factory: Callable[[], Session],
) -> uuid.UUID:
    """The actual background-job worker (plan.md §1) — opens its own session
    rather than reusing the request's (which is already closed by the time
    this runs on the threadpool), resolves the same topics `digest run
    --topic` would, and returns the new Digest's id as the job result."""
    with session_factory() as session:
        user = session.get(User, user_id)
        if topic_name is not None:
            topic = _active_topic_by_name(session, user.id, topic_name)
            if topic is None:
                raise ValueError(f"No active topic named {topic_name!r} for this user.")
            topics = [topic]
        else:
            topics = _active_topics(session, user.id)

        if not topics:
            raise ValueError("No active topics tracked — nothing to run.")

        config = load_config()
        digest = run_digest(session, user, topics, run_type=DigestRunType.ON_DEMAND, config=config)
        return digest.id


@router.post("/run", response_model=JobAcceptedResponse, status_code=202)
def start_digest_run(
    payload: DigestRunRequest,
    background_tasks: BackgroundTasks,
    session_factory: Callable[[], Session] = Depends(get_session_factory),
    user: User = Depends(get_current_user),
) -> JobAcceptedResponse:
    job = registry.create(kind=_JOB_KIND)
    background_tasks.add_task(
        registry.run, job, _run_digest_job, user.id, payload.topic_name, session_factory
    )
    return JobAcceptedResponse(job_id=job.id)


@router.get("/jobs/{job_id}", response_model=DigestJobStatusResponse)
def get_digest_job(
    job_id: uuid.UUID, _user: User = Depends(get_current_user)
) -> DigestJobStatusResponse:
    job = registry.get(job_id)
    if job is None or job.kind != _JOB_KIND:
        raise HTTPException(status_code=404, detail=f"No digest-run job with id {job_id}.")
    digest_id = job.result if job.status == JobStatus.COMPLETED else None
    return DigestJobStatusResponse(status=job.status.value, digest_id=digest_id, error=job.error)
