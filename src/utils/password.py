"""bcrypt password hashing (specs/003-web-dashboard) — the web dashboard's
per-user login credential (User Story 5 / FR-015: real per-user accounts,
replacing the single shared dashboard password).

Deliberately a pure, dependency-free-of-the-rest-of-the-app module: both
`src/cli/user.py` (creates/updates a `User`'s password) and `src/web/auth.py`
(verifies a login attempt) need it, and the CLI must never import from the
web layer, so this lives outside `src/web/` rather than inside it. `bcrypt`
directly, not `passlib` — `passlib`'s bcrypt backend does a fragile
version-probe against the `bcrypt` module that's broken on bcrypt>=4.0 (a
still-unfixed, well-known passlib issue), and this module only ever needs
`hashpw`/`checkpw`, none of passlib's other hash schemes or its
`CryptContext` deprecation-rotation machinery.

Note: bcrypt silently truncates input at 72 bytes — not a practical concern
for real passwords, but documented here so it's never "rediscovered" as a
bug later.
"""

from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    """Hash `password` for storage in `User.password_hash`. Never store or
    log the plaintext `password` itself — only this hash."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check `password` against a hash previously produced by
    `hash_password`. Returns `False` (never raises) for a malformed/foreign
    hash format — a login attempt should 401, not 500, on bad stored data."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False
