"""Env-var-only config loader (tasks.md T021, FR-021, Constitution V).

Every external-service credential lives only in an environment variable and
is checked eagerly here — never hardcoded, never silently defaulted. Missing
a required one fails fast with a clear message naming exactly which var is
missing, rather than surfacing as a confusing downstream API error.

The Claude model name is app config, not a credential, so it *does* have a
default and does not fail fast — it is a runtime-configurable setting read by
Summarize/Draft Post (T040/T056), sourced here so neither module hardcodes a
model name (research.md §3, /speckit-analyze finding E1).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DEFAULT_CLAUDE_MODEL = "claude-sonnet-5"

_REQUIRED_CREDENTIAL_VARS = (
    "TWITTERAPI_IO_KEY",
    "ANTHROPIC_API_KEY",
    "RESEND_API_KEY",
    "X_API_KEY",
    "X_API_SECRET",
    "X_ACCESS_TOKEN",
    "X_ACCESS_TOKEN_SECRET",
)


class ConfigError(RuntimeError):
    """Raised when a required credential env var is missing or empty."""


@dataclass(frozen=True)
class Config:
    twitterapi_io_key: str
    anthropic_api_key: str
    resend_api_key: str
    x_api_key: str
    x_api_secret: str
    x_access_token: str
    x_access_token_secret: str
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
        x_api_key=env["X_API_KEY"],
        x_api_secret=env["X_API_SECRET"],
        x_access_token=env["X_ACCESS_TOKEN"],
        x_access_token_secret=env["X_ACCESS_TOKEN_SECRET"],
        claude_model=env.get("XHF_CLAUDE_MODEL", DEFAULT_CLAUDE_MODEL),
    )
