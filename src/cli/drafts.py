"""`drafts list [--status <status>]` and `drafts mark-published <draft-id>`
CLI commands (tasks.md T064, contracts/cli-commands.md).

This is how a user finds what's `held_manual` and needs to be published by
hand during the 3-week window, or reviews anything `held_below_threshold` /
`publish_failed` after the autonomous switch (FR-019).

IMPORTANT: `mark-published` does NOT post anything to X. It only records,
after the fact, that you already posted a `held_manual` draft yourself. There
is no automated posting path for manually-held drafts by design (that's what
distinguishes manual mode from autonomous mode) — see `src/posting/publish.py`
for the only code path that actually calls the X API. Confusing the two once
led to a draft being recorded as published before it had actually been
posted; the interactive confirmation below exists to prevent that happening
silently again.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import UTC, datetime

from src.cli._common import NoCurrentUserError, resolve_current_user
from src.db.scoped import scoped_select
from src.db.session import get_session
from src.logging_config import configure_logging
from src.models.draft_post import DraftPost, DraftPostStatus


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


def _confirm_already_posted(draft: DraftPost) -> bool:
    """Interactively require the caller to affirm they already posted `draft`
    to X themselves, before we record it as such.

    There is no way for this command to verify that a post actually
    happened — a `published_manual` draft never gets a `tweet_id`/`tweet_url`
    captured, unlike `published_auto`/`published_manual_override` where this
    system made the API call itself (src/models/draft_post.py) — so this is
    a confirmation gate, not a verification. Its only job is to make sure
    "run mark-published" and "actually post to X" are never conflated in the
    moment, which is what caused a draft to be recorded as published before
    it had been.
    """
    print(
        "This will mark the draft below as PUBLISHED without posting it to X — "
        "it only records that you already posted it yourself.",
        file=sys.stderr,
    )
    print(f"    draft_id: {draft.id}", file=sys.stderr)
    print(f"    text: {draft.draft_text}", file=sys.stderr)
    try:
        answer = input("Type 'yes' to confirm this is already live on X: ")
    except EOFError:
        return False
    return answer.strip().lower() == "yes"


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
        if draft.tweet_url:
            print(f"    tweet_url: {draft.tweet_url}")
        if draft.publish_error:
            print(f"    publish_error: {draft.publish_error}")


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="drafts",
        description=(
            "Manage draft posts. NOTE: 'mark-published' never posts to X — it only "
            "records that you already posted a held_manual draft yourself."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument(
        "--status", dest="status", default=None, choices=[s.value for s in DraftPostStatus]
    )

    mark_parser = subparsers.add_parser(
        "mark-published",
        help=(
            "Record that you already posted a held_manual draft to X yourself. Does NOT "
            "post anything."
        ),
        description=(
            "Record that a held_manual draft was already posted to X by you, manually. "
            "This command does NOT call the X API and does NOT post anything on your "
            "behalf — it only updates this draft's status to 'published_manual' and "
            "stamps published_at. Only run it after the content is actually live on X."
        ),
    )
    mark_parser.add_argument("draft_id")
    mark_parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help=(
            "Skip the interactive confirmation prompt (for scripting). You are still "
            "asserting that you already posted this draft to X yourself."
        ),
    )

    args = parser.parse_args(argv)

    with get_session() as session:
        try:
            user = resolve_current_user(session)
        except NoCurrentUserError as exc:
            print(f"Error: {exc}", file=sys.stderr)
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

                pending = _draft_for_user(session, user.id, draft_id)
                if pending is None:
                    print(
                        f"Error: No draft found with id {draft_id} for this user.",
                        file=sys.stderr,
                    )
                    return 1
                if pending.status != DraftPostStatus.HELD_MANUAL:
                    print(
                        f"Error: Draft {draft_id} is '{pending.status.value}', not "
                        "'held_manual' — only manually-held drafts can be marked published "
                        "this way.",
                        file=sys.stderr,
                    )
                    return 1

                if not args.yes and not _confirm_already_posted(pending):
                    print("Aborted: draft was NOT marked as published.", file=sys.stderr)
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
