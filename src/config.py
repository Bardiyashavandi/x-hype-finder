"""Env-var-only config loader (tasks.md T021, FR-021, Constitution V).

Every external-service credential lives only in an environment variable and
is checked eagerly here — never hardcoded, never silently defaulted. Missing
a required one fails fast with a clear message naming exactly which var is
missing, rather than surfacing as a confusing downstream API error.

The Claude model name is app config, not a credential, so it *does* have a
default and does not fail fast — it is a runtime-configurable setting read by
Summarize/Draft Post (T040/T056), sourced here so neither module hardcodes a
model name (research.md §3, /speckit-analyze finding E1).

`Config` holds only the credentials this app's own service accounts use
(TwitterAPI.io read access, the Claude API, Resend) — these are shared across
every user's run because they belong to the app, not to a user. X OAuth
posting credentials are different: each user posts as their *own* X account
(`User.x_account_handle`, data-model.md), so those live in per-user-namespaced
env vars and are loaded separately via `load_x_credentials_for_user` (tasks.md
T067, FR-015, FR-021) — never folded into the one shared `Config`, since doing
so would mean every user's autonomous posting reused the same X credentials.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dotenv import load_dotenv

if TYPE_CHECKING:
    from src.models.user import User

DEFAULT_CLAUDE_MODEL = "claude-sonnet-5"

_REQUIRED_CREDENTIAL_VARS = (
    "TWITTERAPI_IO_KEY",
    "ANTHROPIC_API_KEY",
    "RESEND_API_KEY",
)


class ConfigError(RuntimeError):
    """Raised when a required credential env var is missing or empty."""


@dataclass(frozen=True)
class Config:
    twitterapi_io_key: str
    anthropic_api_key: str
    resend_api_key: str
    claude_model: str


def load_config(*, env: dict[str, str] | None = None) -> Config:
    """Load and validate config from the environment.

    Loads `.env` (via python-dotenv) into `os.environ` first, unless an
    explicit `env` mapping is passed (e.g. by tests), in which case that
    mapping is used as-is and `.env`/the real environment are not consulted.
    """
    if env is None:
        load_dotenv()
        env = os.environ  # type: ignore[assignment]

    missing = [name for name in _REQUIRED_CREDENTIAL_VARS if not env.get(name)]
    if missing:
        raise ConfigError(
            "Missing required environment variable(s): "
            + ", ".join(missing)
            + ". Copy .env.example to .env and fill them in (FR-021 — credentials "
            "are never hardcoded)."
        )

    return Config(
        twitterapi_io_key=env["TWITTERAPI_IO_KEY"],
        anthropic_api_key=env["ANTHROPIC_API_KEY"],
        resend_api_key=env["RESEND_API_KEY"],
        claude_model=env.get("XHF_CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL),
    )


@dataclass(frozen=True)
class XCredentials:
    """One user's own X OAuth 1.0a user-context credentials — never shared
    with another user (FR-015, User Story 5)."""

    api_key: str
    api_secret: str
    access_token: str
    access_token_secret: str


def _env_namespace(x_account_handle: str) -> str:
    """Turn an X handle into an env-var-safe suffix, e.g. `pilot_two` -> `PILOT_TWO`."""
    return re.sub(r"[^A-Za-z0-9]+", "_", x_account_handle).strip("_").upper()


def load_x_credentials_for_user(
    user: "User", *, env: dict[str, str] | None = None
) -> XCredentials:
    """Load `user`'s own X posting credentials from per-user-namespaced env
    vars — `X_API_KEY__<HANDLE>`, `X_API_SECRET__<HANDLE>`,
    `X_ACCESS_TOKEN__<HANDLE>`, `X_ACCESS_TOKEN_SECRET__<HANDLE>`, where
    `<HANDLE>` is `user.x_account_handle` upper-cased with non-alphanumerics
    collapsed to `_` (e.g. `X_API_KEY__PILOT`).

    Deliberately has no fallback to a shared/unnamespaced credential set: a
    silent fallback would mean a second user with no credentials configured
    yet quietly posts through whichever account's credentials happen to be
    set, which is exactly the cross-user leak FR-015 forbids. Fails fast and
    names the exact missing var(s) instead, consistent with `load_config`.
    """
    if env is None:
        load_dotenv()
        env = os.environ  # type: ignore[assignment]

    namespace = _env_namespace(user.x_account_handle)
    var_names = {
        "api_key": f"X_API_KEY__{namespace}",
        "api_secret": f"X_API_SECRET__{namespace}",
        "access_token": f"X_ACCESS_TOKEN__{namespace}",
        "access_token_secret": f"X_ACCESS_TOKEN_SECRET__{namespace}",
    }
    missing = [var for var in var_names.values() if not env.get(var)]
    if missing:
        raise ConfigError(
            f"Missing X credential env var(s) for user '@{user.x_account_handle}': "
            + ", ".join(missing)
            + ". Each user posts as their own X account, so each needs its own "
            "namespaced X_API_KEY__<HANDLE>/X_API_SECRET__<HANDLE>/"
            "X_ACCESS_TOKEN__<HANDLE>/X_ACCESS_TOKEN_SECRET__<HANDLE> env vars "
            "(FR-015, FR-021) — see .env.example."
        )

    return XCredentials(
        api_key=env[var_names["api_key"]],
        api_secret=env[var_names["api_secret"]],
        access_token=env[var_names["access_token"]],
        access_token_secret=env[var_names["access_token_secret"]],
    )
