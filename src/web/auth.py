"""Per-user login: session-key constant + password verification
(specs/003-web-dashboard, User Story 5 / FR-015).

Session *signing* itself is Starlette's own `SessionMiddleware` (an
itsdangerous-signed HttpOnly cookie, wired up in `src/web/app.py`) — this
module only names the session key every router agrees on
(`SESSION_USER_ID_KEY`, holding the logged-in `User.id`) and verifies a
login attempt's password against that specific user's own bcrypt hash
(`User.password_hash`, set via `python -m src.cli.user create`,
src/utils/password.py). No hand-rolled crypto, no shared/env-var password —
there is no "unconfigured dashboard" state anymore, since credentials live
per-row in the database, not in an env var.
"""

from __future__ import annotations

from src.models.user import User
from src.utils.password import verify_password

# The session key `request.session` carries once a login succeeds
# (src/web/routers/auth.py) — holds the logged-in `User.id` (as a string),
# not just a boolean. `src/web/deps.py`'s `get_current_user` reads it to
# resolve the real logged-in row, never guessing (unlike the CLI's
# single-user auto-resolve, src/cli/_common.py's `resolve_current_user`,
# which this web path deliberately never calls).
SESSION_USER_ID_KEY = "user_id"


def verify_user_password(user: User, candidate: str) -> bool:
    """Check `candidate` against `user`'s own stored hash. Always `False`
    for a user with no `password_hash` yet (a CLI-only account that hasn't
    had `user create` run for it) — never a crash, just "not this account's
    password"."""
    if user.password_hash is None:
        return False
    return verify_password(candidate, user.password_hash)
