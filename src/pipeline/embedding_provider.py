"""Embedding provider abstraction (contracts/external-integrations.md §
Embeddings).

Filter Tier 2's coordinated-content check (src/pipeline/filter.py) and
Cluster (src/pipeline/cluster.py) both need `texts -> vectors` and shouldn't
each hardcode which embedding backend produces those vectors. `EMBEDDING_PROVIDER`
selects the backend at runtime:

- `ollama` (default) — local, free, via src/pipeline/embeddings.py. No API
  key; requires a local Ollama server.
- `voyage` — hosted, via src/pipeline/embeddings_voyage.py (`voyage-4-lite`).
  For users without a local Ollama install. Requires `VOYAGE_API_KEY`.

Resolution happens lazily (`get_embedding_provider()` is called at the point
an embedding call is actually about to be made, not at import time) so
importing Filter/Cluster never requires provider credentials to be set, and
clear-keep/clear-exclude-only runs never pay for provider resolution.
"""

from __future__ import annotations

import functools
import os
from typing import Protocol

from dotenv import load_dotenv

from src.pipeline import embeddings as ollama_embeddings
from src.pipeline import embeddings_voyage as voyage_embeddings

EMBEDDING_PROVIDER_ENV = "EMBEDDING_PROVIDER"
VOYAGE_API_KEY_ENV = "VOYAGE_API_KEY"

OLLAMA_PROVIDER = "ollama"
VOYAGE_PROVIDER = "voyage"
DEFAULT_EMBEDDING_PROVIDER = OLLAMA_PROVIDER
_SUPPORTED_PROVIDERS = (OLLAMA_PROVIDER, VOYAGE_PROVIDER)


class EmbeddingProvider(Protocol):
    """A `texts -> one vector per text, same order` callable — the shape
    both src/pipeline/embeddings.py's `get_embeddings` and
    src/pipeline/embeddings_voyage.py's `get_embeddings` implement."""

    def __call__(self, texts: list[str]) -> list[list[float]]: ...


class EmbeddingProviderError(RuntimeError):
    """Raised when EMBEDDING_PROVIDER names an unsupported provider, or the
    selected provider is missing required credentials."""


def get_embedding_provider(*, env: dict[str, str] | None = None) -> EmbeddingProvider:
    """Resolve `EMBEDDING_PROVIDER` (default "ollama") into a ready-to-call
    `texts -> vectors` function.

    Loads `.env` (via python-dotenv) into `os.environ` first, unless an
    explicit `env` mapping is passed (e.g. by tests), in which case that
    mapping is used as-is and `.env`/the real environment are not consulted —
    same convention as src/config.py's `load_config`.
    """
    if env is None:
        load_dotenv()
        env = os.environ  # type: ignore[assignment]

    provider = (env.get(EMBEDDING_PROVIDER_ENV) or DEFAULT_EMBEDDING_PROVIDER).strip().lower()

    if provider == OLLAMA_PROVIDER:
        return ollama_embeddings.get_embeddings

    if provider == VOYAGE_PROVIDER:
        api_key = env.get(VOYAGE_API_KEY_ENV)
        if not api_key:
            raise EmbeddingProviderError(
                f"{EMBEDDING_PROVIDER_ENV}={VOYAGE_PROVIDER} requires {VOYAGE_API_KEY_ENV} to "
                "be set. Copy .env.example to .env and fill it in, or set "
                f"{EMBEDDING_PROVIDER_ENV}={OLLAMA_PROVIDER} to use the local, free provider "
                "instead."
            )
        return functools.partial(voyage_embeddings.get_embeddings, api_key=api_key)

    raise EmbeddingProviderError(
        f"Unsupported {EMBEDDING_PROVIDER_ENV}={provider!r}. Supported providers: "
        + ", ".join(_SUPPORTED_PROVIDERS)
        + "."
    )
