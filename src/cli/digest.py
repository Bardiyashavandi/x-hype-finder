"""`digest run`/`digest show` CLI commands (tasks.md T045, T052 [partial];
contracts/cli-commands.md).

`run` triggers an on-demand pipeline run for all of a user's active topics,
invoking the exact same orchestrator entry point (`src.pipeline.orchestrator.
run_digest`) the scheduler (`src/scheduler/jobs.py`) uses for scheduled runs
— guaranteeing on-demand output format/quality matches a scheduled run
(User Story 2, Acceptance Scenario 2). Single-topic `--topic` scoping is
added in a later phase (US2, T049).

`show` is a **minimal, partial implementation of T052** (User Story 3) — just
enough to print a digest's ranked themes (summary, rationale, confidence,
rank, 3-5 example posts) so US1's output can actually be inspected. It does
not yet implement `--topic` scoping or `--full` drill-down into every
underlying `SourcePost` plus its `filter_outcome` trail — that's the rest of
T052, to be built out with the rest of User Story 3.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select

from src.config import load_config
from src.db.session import get_session
from src.logging_config import configure_logging
from src.models.digest import Digest, DigestRunType
from src.models.digest_topic_result import DigestTopicOutcome, DigestTopicResult
from src.models.source_post import SourcePost
from src.models.theme import Theme
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


def _digest_for_user(session, user_id, digest_id: uuid.UUID) -> Digest | None:
    return session.execute(
        select(Digest).where(Digest.id == digest_id, Digest.user_id == user_id)
    ).scalar_one_or_none()


def _print_digest(session, digest: Digest) -> None:
    print(f"Digest {digest.id}")
    print(f"  status:       {digest.status.value}")
    print(f"  run_type:     {digest.run_type.value}")
    print(f"  started_at:   {digest.started_at.isoformat()}")
    completed_at = digest.completed_at.isoformat() if digest.completed_at else "-"
    print(f"  completed_at: {completed_at}")
    print()

    themed_rows = session.execute(
        select(Theme, Topic.name)
        .join(DigestTopicResult, Theme.digest_topic_result_id == DigestTopicResult.id)
        .join(Topic, DigestTopicResult.topic_id == Topic.id)
        .where(DigestTopicResult.digest_id == digest.id)
        .order_by(Theme.rank)
    ).all()

    if not themed_rows:
        print("No themes in this digest.")
    for theme, topic_name in themed_rows:
        print(
            f"[rank {theme.rank}] {topic_name}  "
            f"confidence={theme.confidence_score}  "
            f"is_spike={theme.is_spike}  spike_ratio={theme.spike_ratio}"
        )
        print(f"    summary:   {theme.summary}")
        print(f"    rationale: {theme.rationale}")

        examples = (
            session.execute(
                select(SourcePost).where(SourcePost.theme_id == theme.id, SourcePost.is_example)
            )
            .scalars()
            .all()
        )
        print(f"    examples ({len(examples)} of {theme.cluster_post_count}):")
        for post in examples:
            print(f"      - @{post.author_handle}: {post.text}")
        print()

    no_theme_rows = session.execute(
        select(DigestTopicResult, Topic.name)
        .join(Topic, DigestTopicResult.topic_id == Topic.id)
        .where(
            DigestTopicResult.digest_id == digest.id,
            DigestTopicResult.outcome != DigestTopicOutcome.THEMES_PRESENT,
        )
    ).all()
    if no_theme_rows:
        print("Topics with no themes this run:")
        for dtr, topic_name in no_theme_rows:
            detail = f" ({dtr.error_detail})" if dtr.error_detail else ""
            print(f"  - {topic_name}: {dtr.outcome.value}{detail}")


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="digest")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("run")
    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("digest_id")

    args = parser.parse_args(argv)

    with get_session() as session:
        user = session.execute(select(User)).scalars().first()
        if user is None:
            print("No user configured — create a User row first.", file=sys.stderr)
            return 1

        if args.command == "run":
            config = load_config()
            topics = _active_topics(session, user.id)
            if not topics:
                print("No active topics tracked — nothing to run.")
                return 0

            digest = run_digest(
                session, user, topics, run_type=DigestRunType.ON_DEMAND, config=config
            )
            print(f"Digest {digest.id} completed with status '{digest.status.value}'")
            return 0

        if args.command == "show":
            try:
                digest_id = uuid.UUID(args.digest_id)
            except ValueError:
                print(f"Invalid digest id: {args.digest_id!r}", file=sys.stderr)
                return 1

            digest = _digest_for_user(session, user.id, digest_id)
            if digest is None:
                print(f"No digest found with id {digest_id} for this user.", file=sys.stderr)
                return 1

            _print_digest(session, digest)
            return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
