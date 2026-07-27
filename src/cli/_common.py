"""Resolve which `User` a CLI process runs as (tasks.md T066, FR-015).

contracts/cli-commands.md: "the process is invoked per-user, scoped by that
user's local credentials/config." Picking an arbitrary row (e.g. the first
`User` in the table) breaks that guarantee the moment a second user exists in
the same database — command output would silently be *someone else's* data
depending on row order, not the invoking user's. `XHF_USER_EMAIL` lets a
process declare which user it is; with exactly one user configured (today's
single/local-dev setup) no env var is needed. With more than one and no env
var set, this refuses to guess rather than risk cross-user leakage.
"""

from __future__ import annotations

import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.user import User

CURRENT_USER_ENV_VAR = "XHF_USER_EMAIL"


class NoCurrentUserError(RuntimeError):
    """Raised when the CLI cannot unambiguously determine which user this
    process is running as."""


def resolve_current_user(session: Session, *, env: dict[str, str] | None = None) -> User:
    """Return the `User` this process is running as.

    - If `XHF_USER_EMAIL` is set, look up that exact user (fails if no user
      has that email — never silently falls back to a different one).
    - Otherwise, if exactly one `User` row exists, use it.
    - Otherwise (zero users, or more than one with no env var set), raise —
      guessing would risk running as, or exposing, another user's data.
    """
    active_env = env if env is not None else os.environ
    email = active_env.get(CURRENT_USER_ENV_VAR)

    if email:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            raise NoCurrentUserError(
                f"No user found with email {email!r} ({CURRENT_USER_ENV_VAR})."
            )
        return user

    users = session.execute(select(User)).scalars().all()
    if len(users) == 1:
        return users[0]
    if not users:
        raise NoCurrentUserError("No user configured — create a User row before using the CLI.")
    raise NoCurrentUserError(
        f"Multiple users configured — set {CURRENT_USER_ENV_VAR} to the email of the user "
        "this process should run as (FR-015 — the CLI must never guess which user's data "
        "to operate on)."
    )
