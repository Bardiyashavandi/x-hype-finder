"""FastAPI app factory for the web dashboard (specs/003-web-dashboard/plan.md §1-2).

`create_app()` wires up session auth (Starlette's `SessionMiddleware` — an
itsdangerous-signed HttpOnly cookie, no hand-rolled crypto), every `/api`
router, and — once `web/dist` exists (`npm run build`) — the compiled SPA,
so one `uvicorn` process serves both (plan.md §2 "Production serving"). It's
a factory rather than a bare module-level `app` so tests can build a fresh
instance per test (with dependency overrides) without needing
`XHF_WEB_SESSION_SECRET` set merely to *import* this module. `src/cli/web.py`
is the `web run` entry point that actually serves this in production.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from src.web.routers import auth, digests, drafts, idea_validate, topics
from src.web.routers import eval as eval_router

# repo_root/web/dist — the compiled SPA. Absent until the frontend is
# actually built (a fresh clone, or this backend's own test suite, never
# runs `npm run build`), so every use of it below is guarded on it existing
# — importing/testing this module must never require the frontend to be
# built first.
WEB_DIST_DIR = Path(__file__).resolve().parents[2] / "web" / "dist"


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

    if WEB_DIST_DIR.is_dir():
        _mount_spa(app)

    return app


def _mount_spa(app: FastAPI) -> None:
    """Serve the built SPA from this same process (plan.md §2). Vite's
    hashed `assets/*` bundle is mounted via `StaticFiles`; every other
    non-`/api` path falls through to `index.html` so react-router-dom's
    client-side routes (`/topics`, `/digests/:id`, ...) work on a hard
    refresh or a direct link, not just client-side navigation — registered
    last, after every `/api/*` router above, so those always match first."""
    app.mount("/assets", StaticFiles(directory=WEB_DIST_DIR / "assets"), name="spa-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            # An unknown API route — a real 404, never the SPA shell.
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = WEB_DIST_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST_DIR / "index.html")
