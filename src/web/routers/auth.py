"""`POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
(specs/003-web-dashboard/plan.md §1 "Auth").
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.web.auth import SESSION_AUTH_KEY, check_password
from src.web.schemas import AuthStatusResponse, LoginRequest

router = APIRouter()


@router.post("/login", response_model=AuthStatusResponse)
def login(payload: LoginRequest, request: Request) -> AuthStatusResponse:
    if not check_password(payload.password):
        raise HTTPException(status_code=401, detail="Incorrect password.")
    request.session[SESSION_AUTH_KEY] = True
    return AuthStatusResponse(authenticated=True)


@router.post("/logout", response_model=AuthStatusResponse)
def logout(request: Request) -> AuthStatusResponse:
    request.session.clear()
    return AuthStatusResponse(authenticated=False)


@router.get("/me", response_model=AuthStatusResponse)
def me(request: Request) -> AuthStatusResponse:
    """The frontend's boot check — never 401s itself, just reports whether
    the session cookie (if any) is authenticated."""
    return AuthStatusResponse(authenticated=bool(request.session.get(SESSION_AUTH_KEY)))
