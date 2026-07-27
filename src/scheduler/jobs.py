"""APScheduler wiring for the default scheduled digest cadence (tasks.md
T047, FR-009 scheduled path, research.md §9).

Drives the exact same orchestrator entry point (`src.pipeline.orchestrator.
run_digest`) the on-demand `digest run` CLI command uses — scheduled and
on-demand runs share one code path by construction, so this module only
supplies the cadence trigger around it.
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
from src.pipeline.orchestrator import run_digest

# Default daily cadence (plan.md Performance Goals); user-configurable via
# the `cadence_hours` argument to `start_scheduler`.
DEFAULT_CADENCE_HOURS = 24

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


def start_scheduler(
    config: Config, *, cadence_hours: int = DEFAULT_CADENCE_HOURS
) -> BackgroundScheduler:
    """Start the in-process scheduler driving the default daily cadence —
    same long-lived process as everything else (research.md §9), no
    external cron/daemon setup required."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_scheduled_digest_for_all_users,
        trigger=IntervalTrigger(hours=cadence_hours),
        args=[config],
        id="scheduled_digest_run",
        replace_existing=True,
    )
    scheduler.start()
    return scheduler
