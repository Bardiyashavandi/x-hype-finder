"""FastAPI app factory for the web dashboard (specs/003-web-dashboard/plan.md §1).

`create_app()` wires up session auth (Starlette's `SessionMiddleware` — an
itsdangerous-signed HttpOnly cookie, no hand-rolled crypto) and every router.
It's a factory rather than a bare module-level `app` so tests can build a
fresh instance per test (with dependency overrides) without needing
`XHF_WEB_PASSWORD`/`XHF_WEB_SESSION_SECRET` set merely to *import* this
module. A later step (`src/cli/web.py`, plan.md §2 "Production serving")
adds the `uvicorn src.web.app:app` entry point and the compiled-SPA static
mount; this module only needs to serve `/api` for now.
"""

from __future__ import annotations

import os

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware

from src.web.routers import auth, digests, drafts, idea_validate, topics
from src.web.routers import eval as eval_router


class WebConfigError(RuntimeError):
    """Raised when a required web-only env var is missing."""


def create_app(*, env: dict[str, str] | None = None) -> FastAPI:
    active_env = env if env is not None else os.environ
    session_secret = active_env.get("XHF_WEB_SESSION_SECRET")
    if not session_secret:
        raise WebConfigError(
            "XHF_WEB_SESSION_SECRET is not set — required to sign the dashboard's session "
            "cookie. Copy .env.example to .env and set it."
        )

    app = FastAPI(title="X Hype Finder — Web Dashboard")
    app.add_middleware(
        SessionMiddleware, secret_key=session_secret, https_only=False, same_site="lax"
    )

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(topics.router, prefix="/api/topics", tags=["topics"])
    app.include_router(digests.router, prefix="/api/digests", tags=["digests"])
    app.include_router(drafts.router, prefix="/api/drafts", tags=["drafts"])
    app.include_router(eval_router.router, prefix="/api/eval", tags=["eval"])
    app.include_router(idea_validate.router, prefix="/api/idea-validate", tags=["idea-validate"])

    return app
