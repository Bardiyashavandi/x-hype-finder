"""Digest run orchestrator (tasks.md T043/T050/T057, contracts/pipeline-stages.md,
FR-017).

Wires Fetch → Filter → Detect → Cluster → Summarize → Rank → Draft Post into
`Digest` / `DigestTopicResult` / `Theme` / `SourcePost` / `DraftPost` writes
for one run, covering every `DigestTopicResult.outcome` explicitly per topic
(`themes_present`/`no_significant_activity`/`all_filtered_as_noise`/
`fetch_error`/`incomplete_rate_limited`) so a topic never silently vanishes
from a digest (FR-017). One topic's failure — expected (a fetch error) or
unexpected (an unhandled exception mid-processing) — never halts the run for
other topics (FR-002).

Rank runs once, across every Theme produced for every topic in the run
(contracts/pipeline-stages.md § Rank — not per-topic), after all topics have
been processed. The digest-completion notification (FR-023) is sent from
here so scheduled and on-demand runs (this is the same entry point both the
CLI and the scheduler call) get identical behavior for free.

Every Theme produced also gets a `DraftPost` (T057) — the PRD's "every stage
is built and ready from day one, including confidence-gated autonomous
posting logic" — with `status` assigned exactly once at creation from the
`PostingMode` in effect at that instant (data-model.md's state machine),
never changed retroactively by a later mode switch (FR-010 edge case). The
user's `PostingMode` row is lazily created on first use, anchoring
`validation_period_ends_at` to this, their first digest run (data-model.md).

Run duration is logged (not enforced — no run is aborted for running long)
against the <5 minute on-demand single-topic budget (FR-009, SC-004), using
`Digest.started_at`/`completed_at` which are already persisted either way.
"""

from __future__ import annotations

from datetime import UTC, datetime

import tweepy
from sqlalchemy.orm import Session

from src.agent.draft_post import DraftPostError, DraftPostInput, generate_draft_post
from src.agent.summarize import SummarizeError, SummarizeInput, summarize_theme
from src.config import Config, load_x_credentials_for_user
from src.db.scoped import scoped_select
from src.logging_config import get_logger
from src.models.digest import Digest, DigestRunType, DigestStatus
from src.models.digest_topic_result import DigestTopicOutcome, DigestTopicResult
from src.models.draft_post import DraftPost
from src.models.posting_mode import PostingMode
from src.models.source_post import FilterOutcome, SourcePost
from src.models.theme import Theme
from src.models.topic import Topic
from src.models.topic_baseline_snapshot import TopicBaselineSnapshot
from src.models.user import User
from src.notify.email import send_digest_completion_notification
from src.pipeline.baseline import prune_source_posts_for_topic, write_baseline_snapshot
from src.pipeline.cluster import ThemeCandidate, cluster_posts
from src.pipeline.detect import DetectResult, detect_spike
from src.pipeline.fetch import FetchErrorKind, RawPost, fetch_topic_posts
from src.pipeline.filter import FilteredPost, filter_posts
from src.pipeline.rank import rank_themes
from src.posting.bio_check import build_x_client
from src.posting.mode import get_or_create_posting_mode
from src.posting.publish import decide_and_publish

# 3-5 curated examples per Theme shown by default (FR-008); a smaller cluster
# has every post flagged as an example instead.
_MIN_EXAMPLE_POSTS = 3
_MAX_EXAMPLE_POSTS = 5

_FAILURE_OUTCOMES = frozenset(
    {DigestTopicOutcome.FETCH_ERROR, DigestTopicOutcome.INCOMPLETE_RATE_LIMITED}
)

# On-demand single-topic budget (FR-009, SC-004) — logged against, not enforced
# (a run is never aborted mid-flight for running long; this only makes the
# budget's health visible after the fact, per tasks.md T050).
ON_DEMAND_SINGLE_TOPIC_BUDGET_SECONDS = 300


def run_digest(
    session: Session,
    user: User,
    topics: list[Topic],
    *,
    run_type: DigestRunType,
    config: Config,
) -> Digest:
    """Run Fetch→Filter→Detect→Cluster→Summarize→Rank for every topic in
    `topics`, persisting one Digest for this run, then send the
    digest-completion notification (FR-023).

    `topics` is caller-scoped (e.g. a user's active topics, or a single
    `--topic`-selected one for on-demand runs) — this function does not
    itself query or filter topics by status.
    """
    log = get_logger(__name__, user_id=str(user.id))
    digest = Digest(
        user_id=user.id,
        run_type=run_type,
        started_at=datetime.now(UTC),
        status=DigestStatus.COMPLETED,  # placeholder — finalized below
    )
    session.add(digest)
    session.flush()  # populate digest.id (Python-side uuid4 defaults resolve at flush)

    # T057: lazily created on first use — validation_period_ends_at anchors
    # to this user's first-ever digest run (data-model.md § PostingMode).
    posting_mode = get_or_create_posting_mode(session, user, now=digest.started_at)
    # This user's own X credentials, never another user's (FR-015) — the
    # scheduler drives this same function once per user (src/scheduler/jobs.py),
    # so this must be resolved fresh per `user`, not taken from the shared `config`.
    x_client = build_x_client(load_x_credentials_for_user(user))

    all_themes: list[Theme] = []
    outcomes: list[DigestTopicOutcome] = []

    for topic in topics:
        topic_log = get_logger(
            __name__, user_id=str(user.id), topic=topic.name, digest_id=str(digest.id)
        )
        dtr, themes = _process_topic(
            session, user, topic, digest, config, posting_mode, x_client, topic_log
        )
        outcomes.append(dtr.outcome)
        all_themes.extend(themes)

    rank_themes(all_themes)

    digest.status = _final_status(outcomes)
    digest.completed_at = datetime.now(UTC)
    session.commit()

    _log_run_duration(log, digest, run_type, topic_count=len(topics))

    try:
        sent = send_digest_completion_notification(digest, user, api_key=config.resend_api_key)
        if sent:
            session.commit()
    except Exception:  # noqa: BLE001 - notification failure must never fail the run (FR-023)
        log.exception("digest-completion notification raised unexpectedly (non-blocking)")

    return digest


def _log_run_duration(log, digest: Digest, run_type: DigestRunType, *, topic_count: int) -> None:
    """Log the run's wall-clock duration (`Digest.started_at`/`completed_at`
    already capture it — no new field needed) and flag on-demand single-topic
    runs that blew the <5 minute budget (FR-009, SC-004, tasks.md T050)."""
    duration_seconds = (digest.completed_at - digest.started_at).total_seconds()
    log.info("digest run completed in %.1fs (run_type=%s)", duration_seconds, run_type.value)

    is_on_demand_single_topic = run_type == DigestRunType.ON_DEMAND and topic_count == 1
    if is_on_demand_single_topic and duration_seconds > ON_DEMAND_SINGLE_TOPIC_BUDGET_SECONDS:
        log.warning(
            "on-demand single-topic run exceeded the %ss budget: took %.1fs",
            ON_DEMAND_SINGLE_TOPIC_BUDGET_SECONDS,
            duration_seconds,
        )


def _final_status(outcomes: list[DigestTopicOutcome]) -> DigestStatus:
    if not outcomes:
        return DigestStatus.COMPLETED
    failures = [o for o in outcomes if o in _FAILURE_OUTCOMES]
    if not failures:
        return DigestStatus.COMPLETED
    if len(failures) == len(outcomes):
        return DigestStatus.FAILED
    return DigestStatus.PARTIAL


def _process_topic(
    session: Session,
    user: User,
    topic: Topic,
    digest: Digest,
    config: Config,
    posting_mode: PostingMode,
    x_client: tweepy.Client,
    log,
) -> tuple[DigestTopicResult, list[Theme]]:
    try:
        return _run_topic_pipeline(
            session, user, topic, digest, config, posting_mode, x_client, log
        )
    except Exception as exc:  # noqa: BLE001 - one topic's failure never halts the run (FR-002)
        log.exception("unexpected error processing topic %s", topic.name)
        dtr = DigestTopicResult(
            digest_id=digest.id,
            topic_id=topic.id,
            outcome=DigestTopicOutcome.FETCH_ERROR,
            error_detail=f"unexpected processing error: {exc}",
        )
        session.add(dtr)
        return dtr, []


def _run_topic_pipeline(
    session: Session,
    user: User,
    topic: Topic,
    digest: Digest,
    config: Config,
    posting_mode: PostingMode,
    x_client: tweepy.Client,
    log,
) -> tuple[DigestTopicResult, list[Theme]]:
    fetch_result = fetch_topic_posts(topic.name, topic.x_handles, api_key=config.twitterapi_io_key)

    if not fetch_result.ok:
        outcome = (
            DigestTopicOutcome.INCOMPLETE_RATE_LIMITED
            if fetch_result.error.kind == FetchErrorKind.RATE_LIMITED
            else DigestTopicOutcome.FETCH_ERROR
        )
        log.error("fetch failed for topic %s: %s", topic.name, fetch_result.error.detail)
        dtr = DigestTopicResult(
            digest_id=digest.id,
            topic_id=topic.id,
            outcome=outcome,
            error_detail=fetch_result.error.detail,
        )
        session.add(dtr)
        return dtr, []

    raw_posts = fetch_result.posts or []

    if not raw_posts:
        dtr = DigestTopicResult(
            digest_id=digest.id,
            topic_id=topic.id,
            outcome=DigestTopicOutcome.NO_SIGNIFICANT_ACTIVITY,
        )
        session.add(dtr)
        write_baseline_snapshot(session, topic.id, 0)
        prune_source_posts_for_topic(session, topic.id)
        return dtr, []

    filtered = filter_posts(raw_posts)
    kept = [f for f in filtered if f.filter_outcome == FilterOutcome.KEPT]

    if not kept:
        dtr = DigestTopicResult(
            digest_id=digest.id, topic_id=topic.id, outcome=DigestTopicOutcome.ALL_FILTERED_AS_NOISE
        )
        session.add(dtr)
        session.flush()  # populate dtr.id before building SourcePost rows that reference it
        for f in filtered:
            session.add(_build_source_post(topic.id, dtr.id, f))
        write_baseline_snapshot(session, topic.id, 0)
        prune_source_posts_for_topic(session, topic.id)
        return dtr, []

    dtr = DigestTopicResult(
        digest_id=digest.id, topic_id=topic.id, outcome=DigestTopicOutcome.THEMES_PRESENT
    )
    session.add(dtr)
    session.flush()  # populate dtr.id before building SourcePost/Theme rows that reference it

    baseline_snapshots = (
        session.execute(
            scoped_select(TopicBaselineSnapshot, user.id).where(
                TopicBaselineSnapshot.topic_id == topic.id
            )
        )
        .scalars()
        .all()
    )
    detect_result = detect_spike(topic, len(kept), baseline_snapshots)

    source_post_by_x_post_id: dict[str, SourcePost] = {}
    for f in filtered:
        sp = _build_source_post(topic.id, dtr.id, f)
        session.add(sp)
        source_post_by_x_post_id[f.post.x_post_id] = sp

    kept_posts = [f.post for f in kept]
    candidates = cluster_posts(kept_posts)
    filter_survival_rate = len(kept) / len(raw_posts)

    themes = _summarize_candidates(
        candidates,
        topic=topic,
        dtr=dtr,
        detect_result=detect_result,
        filter_survival_rate=filter_survival_rate,
        source_post_by_x_post_id=source_post_by_x_post_id,
        session=session,
        user=user,
        posting_mode=posting_mode,
        x_client=x_client,
        config=config,
        log=log,
    )

    write_baseline_snapshot(session, topic.id, len(kept))
    prune_source_posts_for_topic(session, topic.id)
    return dtr, themes


def _summarize_candidates(
    candidates: list[ThemeCandidate],
    *,
    topic: Topic,
    dtr: DigestTopicResult,
    detect_result: DetectResult,
    filter_survival_rate: float,
    source_post_by_x_post_id: dict[str, SourcePost],
    session: Session,
    user: User,
    posting_mode: PostingMode,
    x_client: tweepy.Client,
    config: Config,
    log,
) -> list[Theme]:
    themes: list[Theme] = []

    for candidate in candidates:
        account_diversity = len({post.author_handle for post in candidate.posts})
        try:
            summary = summarize_theme(
                SummarizeInput(
                    topic_name=topic.name,
                    post_texts=[post.text for post in candidate.posts],
                    spike_ratio=detect_result.spike_ratio,
                    cluster_post_count=candidate.post_count,
                    filter_survival_rate=filter_survival_rate,
                    account_diversity_count=account_diversity,
                ),
                api_key=config.anthropic_api_key,
                model=config.claude_model,
            )
        except SummarizeError as exc:
            log.error("Summarize failed for a theme in topic %s: %s", topic.name, exc)
            continue

        theme = Theme(
            digest_topic_result_id=dtr.id,
            summary=summary.summary,
            rationale=summary.rationale,
            confidence_score=summary.confidence_score,
            is_spike=detect_result.is_spike,
            spike_ratio=detect_result.spike_ratio,
            cluster_post_count=candidate.post_count,
            rank=0,  # placeholder — assigned once across the whole run by rank_themes
        )
        session.add(theme)
        session.flush()  # populate theme.id before assigning it as SourcePost.theme_id
        themes.append(theme)

        example_ids = _select_example_post_ids(candidate)
        for post in candidate.posts:
            sp = source_post_by_x_post_id[post.x_post_id]
            sp.theme_id = theme.id
            sp.is_example = post.x_post_id in example_ids

        example_texts = [post.text for post in candidate.posts if post.x_post_id in example_ids]
        _create_draft_post(
            session,
            user=user,
            topic=topic,
            theme=theme,
            example_post_texts=example_texts,
            posting_mode=posting_mode,
            x_client=x_client,
            config=config,
            log=log,
        )

    return themes


def _create_draft_post(
    session: Session,
    *,
    user: User,
    topic: Topic,
    theme: Theme,
    example_post_texts: list[str],
    posting_mode: PostingMode,
    x_client: tweepy.Client,
    config: Config,
    log,
) -> DraftPost | None:
    """Generate a DraftPost for `theme` and assign its `status` exactly once,
    per the PostingMode in effect right now (T057, data-model.md). A Draft
    Post failure only skips this theme's draft — the Theme itself still
    appears in the digest either way (contracts/external-integrations.md § LLM)."""
    try:
        draft_result = generate_draft_post(
            DraftPostInput(
                topic_name=topic.name,
                theme_summary=theme.summary,
                theme_rationale=theme.rationale,
                example_post_texts=example_post_texts,
            ),
            api_key=config.anthropic_api_key,
            model=config.claude_model,
        )
    except DraftPostError as exc:
        log.error("Draft Post failed for a theme in topic %s: %s", topic.name, exc)
        return None

    outcome = decide_and_publish(
        session,
        posting_mode,
        confidence_score=theme.confidence_score,
        draft_text=draft_result.draft_text,
        x_client=x_client,
    )
    draft = DraftPost(
        theme_id=theme.id,
        user_id=user.id,
        draft_text=draft_result.draft_text,
        confidence_score=theme.confidence_score,
        status=outcome.status,
        published_at=outcome.published_at,
        publish_error=outcome.publish_error,
    )
    session.add(draft)
    return draft


def _select_example_post_ids(candidate: ThemeCandidate) -> set[str]:
    """3-5 curated example posts per Theme (FR-008) — or every post, if the
    cluster has fewer than the 3-post minimum to begin with."""
    limit = max(_MIN_EXAMPLE_POSTS, min(_MAX_EXAMPLE_POSTS, candidate.post_count))
    return {post.x_post_id for post in candidate.posts[:limit]}


def _build_source_post(topic_id, digest_topic_result_id, filtered_post: FilteredPost) -> SourcePost:
    post: RawPost = filtered_post.post
    return SourcePost(
        topic_id=topic_id,
        digest_topic_result_id=digest_topic_result_id,
        x_post_id=post.x_post_id,
        author_handle=post.author_handle,
        text=post.text,
        posted_at=post.posted_at,
        filter_outcome=filtered_post.filter_outcome,
    )
