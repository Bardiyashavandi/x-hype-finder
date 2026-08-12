"""FastAPI dependencies shared by every router (specs/003-web-dashboard/plan.md §1).

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

`get_current_user` resolves the acting user via the exact same
`resolve_current_user()` every CLI command uses (plan.md §1 "Which 'current
user'?") — single-user auto-resolve, or `XHF_USER_EMAIL` if ambiguous —
called fresh per request against that request's own session, never cached.
It depends on `require_auth`, so any router using `Depends(get_current_user)`
gets the 401 auth gate for free.
"""

from __future__ import annotations

from collections.abc import Callable, Generator

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.cli._common import NoCurrentUserError, resolve_current_user
from src.db.session import get_session
from src.models.user import User
from src.web.auth import SESSION_AUTH_KEY


def get_db() -> Generator[Session, None, None]:
    session = get_session()
    try:
        yield session
    finally:
        session.close()


def get_session_factory() -> Callable[[], Session]:
    return get_session


def require_auth(request: Request) -> None:
    """401 unless this request's session cookie was set by a successful
    `POST /api/auth/login` — every router but auth depends on this (directly
    or via `get_current_user`)."""
    if not request.session.get(SESSION_AUTH_KEY):
        raise HTTPException(status_code=401, detail="Not authenticated.")


def get_current_user(
    db: Session = Depends(get_db),
    _auth: None = Depends(require_auth),
) -> User:
    try:
        return resolve_current_user(db)
    except NoCurrentUserError as exc:
        # A misconfigured/empty deployment, not a client error — surface it
        # as a 500 rather than a misleading 401/404.
        raise HTTPException(status_code=500, detail=str(exc)) from exc
