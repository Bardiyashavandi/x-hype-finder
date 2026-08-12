"""`POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
(specs/003-web-dashboard, User Story 5 / FR-015: real per-user login).

Accounts are provisioned only via `python -m src.cli.user create <email>`
(src/cli/user.py) — there is no signup endpoint here.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.user import User
from src.web.auth import SESSION_USER_ID_KEY, verify_user_password
from src.web.deps import get_db
from src.web.schemas import AuthStatusResponse, LoginRequest

router = APIRouter()

_INCORRECT_CREDENTIALS_DETAIL = "Incorrect email or password."


@router.post("/login", response_model=AuthStatusResponse)
def login(
    payload: LoginRequest, request: Request, db: Session = Depends(get_db)
) -> AuthStatusResponse:
    # Unscoped by design — this IS identity resolution, the one legitimate
    # place in the app that looks a `User` up by something other than an
    # already-known `user_id` (mirrors `resolve_current_user`'s own
    # unscoped bootstrap query on the CLI side, src/cli/_common.py).
    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()

    # Same generic failure for every case — unknown email, an account with
    # no password_hash yet (CLI-only, never had `user create` run for it),
    # or a wrong password — so a login attempt can never be used to probe
    # which accounts exist (no user-enumeration).
    if user is None or not verify_user_password(user, payload.password):
        raise HTTPException(status_code=401, detail=_INCORRECT_CREDENTIALS_DETAIL)

    request.session[SESSION_USER_ID_KEY] = str(user.id)
    return AuthStatusResponse(authenticated=True, email=user.email)


@router.post("/logout", response_model=AuthStatusResponse)
def logout(request: Request) -> AuthStatusResponse:
    request.session.clear()
    return AuthStatusResponse(authenticated=False)


@router.get("/me", response_model=AuthStatusResponse)
def me(request: Request, db: Session = Depends(get_db)) -> AuthStatusResponse:
    """The frontend's boot check — never 401s itself, just reports whether
    the session resolves to a real, still-existing user. Re-derives
    identity from the database every call rather than trusting a cached
    flag, so a session left over from a since-deleted account self-heals to
    `authenticated: false` (clearing the stale cookie) instead of reporting
    access forever."""
    raw_user_id = request.session.get(SESSION_USER_ID_KEY)
    if raw_user_id is None:
        return AuthStatusResponse(authenticated=False)

    try:
        user_id = uuid.UUID(raw_user_id)
    except (ValueError, TypeError, AttributeError):
        request.session.clear()
        return AuthStatusResponse(authenticated=False)

    user = db.get(User, user_id)
    if user is None:
        request.session.clear()
        return AuthStatusResponse(authenticated=False)

    return AuthStatusResponse(authenticated=True, email=user.email)
