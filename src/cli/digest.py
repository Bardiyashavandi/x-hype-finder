"""`digest run` CLI command (tasks.md T045, contracts/cli-commands.md).

Triggers an on-demand pipeline run for all of a user's active topics,
invoking the exact same orchestrator entry point (`src.pipeline.orchestrator.
run_digest`) the scheduler (`src/scheduler/jobs.py`) uses for scheduled runs
— guaranteeing on-demand output format/quality matches a scheduled run
(User Story 2, Acceptance Scenario 2). Single-topic `--topic` scoping is
added in a later phase (US2, T049).
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from src.config import load_config
from src.db.session import get_session
from src.logging_config import configure_logging
from src.models.digest import DigestRunType
from src.models.topic import Topic, TopicStatus
from src.models.user import User
from src.pipeline.orchestrator import run_digest


def _active_topics(session, user_id) -> list[Topic]:
    return (
        session.execute(
            select(Topic).where(Topic.user_id == user_id, Topic.status == TopicStatus.ACTIVE)
        )
        .scalars()
        .all()
    )


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="digest")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run")

    args = parser.parse_args(argv)
    if args.command != "run":
        parser.print_help()
        return 1

    config = load_config()

    with get_session() as session:
        user = session.execute(select(User)).scalars().first()
        if user is None:
            print(
                "No user configured — create a User row before running a digest.",
                file=sys.stderr,
            )
            return 1

        topics = _active_topics(session, user.id)
        if not topics:
            print("No active topics tracked — nothing to run.")
            return 0

        digest = run_digest(session, user, topics, run_type=DigestRunType.ON_DEMAND, config=config)
        print(f"Digest {digest.id} completed with status '{digest.status.value}'")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
