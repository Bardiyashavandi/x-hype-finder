"""APScheduler wiring for the default scheduled digest cadence (tasks.md
T047, FR-009 scheduled path, research.md §9) and the standalone SourcePost
retention sweep (tasks.md T070, FR-020).

Drives the exact same orchestrator entry point (`src.pipeline.orchestrator.
run_digest`) the on-demand `digest run` CLI command uses — scheduled and
on-demand runs share one code path by construction, so this module only
supplies the cadence trigger around it. The retention sweep
(`prune_stale_source_posts`, src/pipeline/baseline.py) runs on its own
independent cadence, since it isn't tied to any one digest run completing.
"""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from src.config import Config
from src.db.scoped import scoped_select
from src.db.session import get_session
from src.logging_config import get_logger
from src.models.digest import DigestRunType
from src.models.topic import Topic, TopicStatus
from src.models.user import User
from src.pipeline.baseline import prune_stale_source_posts
from src.pipeline.orchestrator import run_digest

# Default daily cadence (plan.md Performance Goals); user-configurable via
# the `cadence_hours` argument to `start_scheduler`.
DEFAULT_CADENCE_HOURS = 24

# The retention window (30 days, src/pipeline/baseline.py) is generous
# relative to how stale rows can get between sweeps, so a daily cadence is
# plenty — configurable via `start_scheduler`'s `retention_sweep_cadence_hours`.
DEFAULT_RETENTION_SWEEP_CADENCE_HOURS = 24

log = get_logger(__name__)


def run_scheduled_digest_for_all_users(config: Config) -> None:
    """The scheduled job body: one Digest run per user with active topics.

    Each user's run is independent — one user's failure must not prevent
    another user's scheduled run from executing, mirroring FR-002's
    per-topic isolation one level up.
    """
    with get_session() as session:
        users = session.execute(select(User)).scalars().all()
        for user in users:
            try:
                topics = (
                    session.execute(
                        scoped_select(Topic, user.id).where(Topic.status == TopicStatus.ACTIVE)
                    )
                    .scalars()
                    .all()
                )
                if not topics:
                    continue
                run_digest(session, user, topics, run_type=DigestRunType.SCHEDULED, config=config)
            except Exception:  # noqa: BLE001 - one user's run must never block another's
                log.exception("scheduled digest run failed for user %s", user.id)


def run_source_post_retention_sweep() -> None:
    """The retention-sweep job body (tasks.md T070, FR-020): delete every
    `SourcePost` row older than the retention window, across every topic and
    user. Independent of any digest run — catches rows a run's own inline
    prune (T042) could miss, e.g. from a run that failed before its prune
    step, or a topic that hasn't run recently."""
    with get_session() as session:
        deleted = prune_stale_source_posts(session)
        session.commit()
        log.info("source post retention sweep deleted %d stale row(s)", deleted)


def start_scheduler(
    config: Config,
    *,
    cadence_hours: int = DEFAULT_CADENCE_HOURS,
    retention_sweep_cadence_hours: int = DEFAULT_RETENTION_SWEEP_CADENCE_HOURS,
) -> BackgroundScheduler:
    """Start the in-process scheduler driving the default daily digest
    cadence and the standalone retention sweep — same long-lived process as
    everything else (research.md §9), no external cron/daemon setup
    required."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_scheduled_digest_for_all_users,
        trigger=IntervalTrigger(hours=cadence_hours),
        args=[config],
        id="scheduled_digest_run",
        replace_existing=True,
    )
    scheduler.add_job(
        run_source_post_retention_sweep,
        trigger=IntervalTrigger(hours=retention_sweep_cadence_hours),
        id="source_post_retention_sweep",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler
