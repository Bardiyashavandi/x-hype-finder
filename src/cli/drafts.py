"""`drafts list [--status <status>]` and `drafts mark-published <draft-id>`
CLI commands (tasks.md T064, contracts/cli-commands.md).

This is how a user finds what's `held_manual` and needs to be published by
hand during the 3-week window, or reviews anything `held_below_threshold` /
`publish_failed` after the autonomous switch (FR-019).
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from src.db.scoped import scoped_select
from src.db.session import get_session
from src.logging_config import configure_logging
from src.models.draft_post import DraftPost, DraftPostStatus
from src.models.user import User


class DraftsCommandError(RuntimeError):
    """Raised for a rejected drafts command (e.g. an unknown id or wrong status)."""


def _draft_for_user(session, user_id, draft_id: uuid.UUID) -> DraftPost | None:
    return session.execute(
        scoped_select(DraftPost, user_id).where(DraftPost.id == draft_id)
    ).scalar_one_or_none()


def list_drafts(session, user_id, *, status: DraftPostStatus | None = None) -> list[DraftPost]:
    stmt = scoped_select(DraftPost, user_id)
    if status is not None:
        stmt = stmt.where(DraftPost.status == status)
    return session.execute(stmt.order_by(DraftPost.created_at)).scalars().all()


def mark_published(session, user_id, draft_id: uuid.UUID) -> DraftPost:
    """Record that the user manually published a `held_manual` draft
    themselves on X (contracts/cli-commands.md § `drafts mark-published`) —
    sets `status = published_manual`, `published_at = now()`."""
    draft = _draft_for_user(session, user_id, draft_id)
    if draft is None:
        raise DraftsCommandError(f"No draft found with id {draft_id} for this user.")
    if draft.status != DraftPostStatus.HELD_MANUAL:
        raise DraftsCommandError(
            f"Draft {draft_id} is '{draft.status.value}', not 'held_manual' — only "
            "manually-held drafts can be marked published this way."
        )
    draft.status = DraftPostStatus.PUBLISHED_MANUAL
    draft.published_at = datetime.now(UTC)
    session.commit()
    return draft


def _print_drafts(drafts: list[DraftPost]) -> None:
    if not drafts:
        print("No drafts found.")
        return
    for draft in drafts:
        published_at = draft.published_at.isoformat() if draft.published_at else "-"
        print(
            f"{draft.id}\tstatus={draft.status.value}\tconfidence={draft.confidence_score}"
            f"\tpublished_at={published_at}"
        )
        print(f"    {draft.draft_text}")
        if draft.publish_error:
            print(f"    publish_error: {draft.publish_error}")


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="drafts")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument(
        "--status", dest="status", default=None, choices=[s.value for s in DraftPostStatus]
    )

    mark_parser = subparsers.add_parser("mark-published")
    mark_parser.add_argument("draft_id")

    args = parser.parse_args(argv)

    with get_session() as session:
        user = session.execute(select(User)).scalars().first()
        if user is None:
            print("No user configured — create a User row first.", file=sys.stderr)
            return 1

        try:
            if args.command == "list":
                status = DraftPostStatus(args.status) if args.status else None
                _print_drafts(list_drafts(session, user.id, status=status))
                return 0

            if args.command == "mark-published":
                try:
                    draft_id = uuid.UUID(args.draft_id)
                except ValueError:
                    print(f"Invalid draft id: {args.draft_id!r}", file=sys.stderr)
                    return 1
                draft = mark_published(session, user.id, draft_id)
                print(f"Marked draft {draft.id} as published_manual.")
                return 0
        except DraftsCommandError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
