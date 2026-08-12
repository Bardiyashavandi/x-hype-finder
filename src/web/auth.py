"""Single-shared-password auth: password check + session-key constant
(specs/003-web-dashboard/plan.md §1 "Auth").

Session *signing* itself is Starlette's own `SessionMiddleware` (an
itsdangerous-signed HttpOnly cookie, wired up in `src/web/app.py`) — this
module only checks the submitted password against `XHF_WEB_PASSWORD` and
names the one session key every router agrees on. No hand-rolled crypto.
"""

from __future__ import annotations

import os
import secrets

# The single key `request.session` carries once a login succeeds
# (src/web/routers/auth.py) — `src/web/deps.py`'s `require_auth` checks it.
SESSION_AUTH_KEY = "authenticated"


class WebAuthConfigError(RuntimeError):
    """Raised when `XHF_WEB_PASSWORD` isn't configured."""


def check_password(candidate: str, *, env: dict[str, str] | None = None) -> bool:
    """`secrets.compare_digest` against `XHF_WEB_PASSWORD` (plan.md §1) —
    constant-time, so a mistyped password can't be distinguished from a
    close-but-wrong one by response timing.

    Returns `False` (never raises) when `XHF_WEB_PASSWORD` itself isn't set —
    an unconfigured dashboard should reject every login attempt, not 500.
    """
    active_env = env if env is not None else os.environ
    expected = active_env.get("XHF_WEB_PASSWORD")
    if not expected:
        return False
    return secrets.compare_digest(candidate, expected)
