"""`user create <email>` CLI command (specs/003-web-dashboard) — provisions
web dashboard accounts (User Story 5 / FR-015: real per-user accounts,
replacing the dashboard's original single shared password).

No public signup flow — this is the only way a dashboard account is ever
created: the operator runs this for themself and, separately, for each
collaborator. Unlike every other `src/cli/*.py` command, this one does NOT
call `resolve_current_user` (src/cli/_common.py) — it edits an identity by
explicit email, it never acts *as* one.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.session import get_session
from src.logging_config import configure_logging
from src.models.user import User
from src.utils.password import hash_password


class UserCommandError(RuntimeError):
    """Raised for a rejected `user` command (e.g. a new email with no --handle)."""


def _find_user_by_email(session: Session, email: str) -> User | None:
    return session.execute(select(User).where(User.email == email)).scalar_one_or_none()


def create_user(session: Session, email: str, password: str, *, handle: str | None = None) -> User:
    """Create a new `User` — `handle` is required in that case, since
    `x_account_handle` has no sensible default to invent — or update an
    existing one's password (and its handle too, if `handle` is given).

    Only ever stores `hash_password(password)` (src/utils/password.py); the
    plaintext `password` itself is never persisted or logged anywhere.
    """
    email = email.strip()
    if not email:
        raise UserCommandError("Email must not be empty.")
    if not password.strip():
        raise UserCommandError("Password must not be empty.")

    user = _find_user_by_email(session, email)
    if user is not None:
        user.password_hash = hash_password(password)
        if handle is not None:
            user.x_account_handle = handle
        session.commit()
        return user

    if handle is None:
        raise UserCommandError(
            f"No user found with email {email!r} — creating a new user requires "
            "--handle <x_account_handle>."
        )

    user = User(email=email, x_account_handle=handle, password_hash=hash_password(password))
    session.add(user)
    session.commit()
    return user


def _prompt_password() -> str | None:
    """Read a password from stdin without echoing it. Returns `None` (never
    raises) on EOF so the caller can abort cleanly — same EOF-safe-prompt
    convention as src/cli/drafts.py's `_confirm_already_posted`."""
    try:
        return getpass.getpass("Password: ")
    except EOFError:
        return None


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="user")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser(
        "create",
        help="Create a new dashboard account, or update an existing one's password.",
    )
    create_parser.add_argument("email")
    create_parser.add_argument(
        "--handle",
        dest="handle",
        default=None,
        help="X account handle — required when creating a brand-new user.",
    )

    args = parser.parse_args(argv)

    password = _prompt_password()
    if password is None:
        print("Error: aborted (no password entered).", file=sys.stderr)
        return 1

    with get_session() as session:
        try:
            if args.command == "create":
                user = create_user(session, args.email, password, handle=args.handle)
                print(f"User {user.email} ready (id={user.id}).")
        except UserCommandError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
