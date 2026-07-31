"""Fetch provider abstraction (contracts/external-integrations.md § X Data Read
Provider), mirroring src/pipeline/embedding_provider.py's shape.

`FETCH_PROVIDER` selects which X data read backend `get_fetch_provider()`
resolves to at runtime:

- `twitterapis_com` (default) — src/pipeline/fetch_twitterapis_com.py.
  Requires `TWITTERAPIS_COM_KEY`. Made default 2026-07-31: a live side-by-side
  comparison (see PR #11 / the follow-up that wired this module in) found it
  faster and at full data parity with TwitterAPI.io, without that provider's
  0.2 QPS free-tier pacing.
- `twitterapi_io` — src/pipeline/fetch.py. Requires `TWITTERAPI_IO_KEY`.

Wired into src/pipeline/orchestrator.py's `_run_topic_pipeline`, which calls
`get_fetch_provider()(topic.name, topic.x_handles)` — every integration test
that stubs Fetch monkeypatches `orchestrator_module.get_fetch_provider`
(returning a `(topic_name, x_handles, **kwargs) -> FetchResult` stub) rather
than a concrete provider's `fetch_topic_posts`.

Resolution happens lazily (`get_fetch_provider()` is called at the point a
fetch call is actually about to be made, not at import time), same rationale
as `get_embedding_provider()`.
"""

from __future__ import annotations

import functools
import os
from datetime import datetime
from typing import Protocol

from dotenv import load_dotenv

from src.pipeline import fetch as twitterapi_io_fetch
from src.pipeline import fetch_twitterapis_com as twitterapis_com_fetch
from src.pipeline.fetch import FetchResult

FETCH_PROVIDER_ENV = "FETCH_PROVIDER"
TWITTERAPI_IO_KEY_ENV = "TWITTERAPI_IO_KEY"
TWITTERAPIS_COM_KEY_ENV = "TWITTERAPIS_COM_KEY"

TWITTERAPI_IO_PROVIDER = "twitterapi_io"
TWITTERAPIS_COM_PROVIDER = "twitterapis_com"
DEFAULT_FETCH_PROVIDER = TWITTERAPIS_COM_PROVIDER
_SUPPORTED_PROVIDERS = (TWITTERAPI_IO_PROVIDER, TWITTERAPIS_COM_PROVIDER)


class FetchProvider(Protocol):
    """The `(topic_name, x_handles, ...) -> FetchResult` shape both
    src/pipeline/fetch.py's and src/pipeline/fetch_twitterapis_com.py's
    `fetch_topic_posts` implement."""

    def __call__(
        self,
        topic_name: str,
        x_handles: list[str],
        *,
        since: datetime | None = None,
        until: datetime | None = None,
        max_posts: int = ...,
        session=None,
    ) -> FetchResult: ...


class FetchProviderError(RuntimeError):
    """Raised when FETCH_PROVIDER names an unsupported provider, or the
    selected provider is missing required credentials."""


def get_fetch_provider(*, env: dict[str, str] | None = None) -> FetchProvider:
    """Resolve `FETCH_PROVIDER` (default "twitterapis_com") into a ready-to-call
    `(topic_name, x_handles, ...) -> FetchResult` function.

    Loads `.env` (via python-dotenv) into `os.environ` first, unless an
    explicit `env` mapping is passed (e.g. by tests), in which case that
    mapping is used as-is and `.env`/the real environment are not consulted —
    same convention as src/config.py's `load_config` and
    src/pipeline/embedding_provider.py's `get_embedding_provider`.
    """
    if env is None:
        load_dotenv()
        env = os.environ  # type: ignore[assignment]

    provider = (env.get(FETCH_PROVIDER_ENV) or DEFAULT_FETCH_PROVIDER).strip().lower()

    if provider == TWITTERAPI_IO_PROVIDER:
        api_key = env.get(TWITTERAPI_IO_KEY_ENV)
        if not api_key:
            raise FetchProviderError(
                f"{FETCH_PROVIDER_ENV}={TWITTERAPI_IO_PROVIDER} requires {TWITTERAPI_IO_KEY_ENV} "
                "to be set. Copy .env.example to .env and fill it in."
            )
        return functools.partial(twitterapi_io_fetch.fetch_topic_posts, api_key=api_key)

    if provider == TWITTERAPIS_COM_PROVIDER:
        api_key = env.get(TWITTERAPIS_COM_KEY_ENV)
        if not api_key:
            raise FetchProviderError(
                f"{FETCH_PROVIDER_ENV}={TWITTERAPIS_COM_PROVIDER} requires "
                f"{TWITTERAPIS_COM_KEY_ENV} to be set. Copy .env.example to .env and fill it in, "
                f"or set {FETCH_PROVIDER_ENV}={TWITTERAPI_IO_PROVIDER} to use the alternative "
                "provider instead."
            )
        return functools.partial(twitterapis_com_fetch.fetch_topic_posts, api_key=api_key)

    raise FetchProviderError(
        f"Unsupported {FETCH_PROVIDER_ENV}={provider!r}. Supported providers: "
        + ", ".join(_SUPPORTED_PROVIDERS)
        + "."
    )
