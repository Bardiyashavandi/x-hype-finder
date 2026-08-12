"""FastAPI dependencies shared by every router (specs/003-web-dashboard).

Two DB-access dependencies, deliberately different lifecycles:

- `get_db` — one request-scoped `Session`, opened and closed around a single
  request. Used by every router that reads/writes synchronously within the
  request itself (auth, topics, drafts, eval, digest listing/detail).
- `get_session_factory` — returns a *callable* that opens a session, for the
  two background-job routers (digests, idea-validate). Their worker function
  runs on FastAPI's threadpool *after* the request that started it has
  already returned, so it cannot reuse that request's session — it opens its
  own via `with session_factory() as session:` instead (same
  context-manager convention `src/cli/*.py` already uses for `get_session()`).

Both are overridden in tests to reuse the shared in-memory `db_session`
fixture (tests/web/conftest.py) rather than hitting a real sqlite file.

`get_current_user` resolves the acting user directly from the session's
stored `user_id` (User Story 5 / FR-015: real per-user login,
specs/003-web-dashboard) — it deliberately does NOT call the CLI's
`resolve_current_user()` (src/cli/_common.py), whose single-user
auto-resolve/`XHF_USER_EMAIL` logic assumes exactly one operator-run process
and doesn't fit a real multi-user browser login: two people logged in at
once, from two different sessions, must each resolve to *their own* row,
not whichever row `resolve_current_user` happens to auto-pick.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Generator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.db.session import get_session
from src.models.user import User
from src.web.auth import SESSION_USER_ID_KEY


def get_db() -> Generator[Session, None, None]:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_session_factory() -> Callable[[], Session]:
    return get_session


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """The `User` this request is logged in as, read straight from the
    session (`SESSION_USER_ID_KEY`) and looked up fresh every request —
    401 if the session carries no user id, an unparseable one, or one that
    no longer resolves to a real row (e.g. the account was deleted after
    the cookie was issued — self-heals rather than trusting a stale
    session forever)."""
    raw_user_id = request.session.get(SESSION_USER_ID_KEY)
    if raw_user_id is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    try:
        user_id = uuid.UUID(raw_user_id)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(status_code=401, detail="Not authenticated.") from None

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated.")
    return user
