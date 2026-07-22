"""`topic add/remove/list` CLI commands (tasks.md T044,
contracts/cli-commands.md, FR-001, SC-001).

The CLI process is invoked per-user (contracts/cli-commands.md) — full
per-user credential/session namespacing lands in a later phase (US5, T067);
for now this picks the single configured `User` row, matching the MVP's
2-user, locally-run scope (plan.md Scale/Scope).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.session import get_session
from src.logging_config import configure_logging
from src.models.topic import Topic, TopicStatus
from src.models.user import User


class TopicCommandError(RuntimeError):
    """Raised for a rejected topic command (e.g. a duplicate active name)."""


def _find_topic(session: Session, user_id, name: str, status: TopicStatus) -> Topic | None:
    return session.execute(
        select(Topic).where(Topic.user_id == user_id, Topic.name == name, Topic.status == status)
    ).scalar_one_or_none()


def add_topic(session: Session, user_id, name: str, x_handles: list[str] | None = None) -> Topic:
    """Create (or reactivate) an active Topic. MUST be visible to the very
    next run with no code change or redeploy (FR-001, SC-001) — this is
    guaranteed for free since the orchestrator always re-queries active
    topics from the DB at run time."""
    name = name.strip()
    if not name:
        raise TopicCommandError("Topic name must not be empty.")

    if _find_topic(session, user_id, name, TopicStatus.ACTIVE) is not None:
        raise TopicCommandError(f"Topic '{name}' is already active for this user.")

    # Re-adding a previously-removed topic reactivates the original row so
    # its baseline/history persists (data-model.md's soft-delete rationale),
    # rather than inserting a duplicate.
    removed = _find_topic(session, user_id, name, TopicStatus.REMOVED)
    if removed is not None:
        removed.status = TopicStatus.ACTIVE
        removed.x_handles = x_handles or []
        session.commit()
        return removed

    topic = Topic(
        user_id=user_id,
        name=name,
        x_handles=x_handles or [],
        status=TopicStatus.ACTIVE,
        first_tracked_at=datetime.now(UTC),
    )
    session.add(topic)
    session.commit()
    return topic


def remove_topic(session: Session, user_id, name: str) -> Topic:
    """Soft-delete: sets `status = removed`. History/baseline rows persist
    (contracts/cli-commands.md); removed topics MUST NOT appear in the next
    run's Digest, which the orchestrator's active-topics query guarantees."""
    topic = _find_topic(session, user_id, name, TopicStatus.ACTIVE)
    if topic is None:
        raise TopicCommandError(f"No active topic named '{name}' for this user.")
    topic.status = TopicStatus.REMOVED
    session.commit()
    return topic


def list_topics(session: Session, user_id) -> list[Topic]:
    return (
        session.execute(
            select(Topic).where(Topic.user_id == user_id, Topic.status == TopicStatus.ACTIVE)
        )
        .scalars()
        .all()
    )


def _print_topics(topics: list[Topic]) -> None:
    for topic in topics:
        in_observation = "yes" if topic.observation_period_active else "no"
        print(
            f"{topic.name}\tfirst_tracked_at={topic.first_tracked_at.isoformat()}"
            f"\tin_observation_period={in_observation}"
        )


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="topic")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("name")
    add_parser.add_argument("--handles", default="", help="comma-separated X handles")

    remove_parser = subparsers.add_parser("remove")
    remove_parser.add_argument("name")

    subparsers.add_parser("list")

    args = parser.parse_args(argv)

    with get_session() as session:
        user = session.execute(select(User)).scalars().first()
        if user is None:
            print("No user configured — create a User row before using the CLI.", file=sys.stderr)
            return 1

        try:
            if args.command == "add":
                handles = [h.strip() for h in args.handles.split(",") if h.strip()]
                topic = add_topic(session, user.id, args.name, handles)
                print(f"Added topic '{topic.name}' (id={topic.id})")
            elif args.command == "remove":
                topic = remove_topic(session, user.id, args.name)
                print(f"Removed topic '{topic.name}'")
            elif args.command == "list":
                _print_topics(list_topics(session, user.id))
        except TopicCommandError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
