"""Ollama embeddings client wrapper (tasks.md T036, contracts/external-integrations.md
§ Embeddings, research.md §4).

Used by Filter Tier 2's coordinated-content check (src/pipeline/filter.py) and,
in a later phase, Cluster. Local-only, no API key — if Ollama is unreachable
this is a local-environment fault, not a per-topic data fault, so it fails
fast with a clear setup error rather than silently degrading filtering/
clustering quality (contracts/external-integrations.md).
"""

from __future__ import annotations

import requests

OLLAMA_BASE_URL = "http://localhost:11434"
EMBED_PATH = "/api/embed"
EMBED_MODEL = "nomic-embed-text"


class OllamaUnavailableError(RuntimeError):
    """Raised when the local Ollama server can't be reached or returns something unusable."""


def get_embeddings(
    texts: list[str],
    *,
    base_url: str = OLLAMA_BASE_URL,
    session: requests.Session | None = None,
) -> list[list[float]]:
    """Return one embedding vector per input text, in the same order.

    Deliberately does not retry — retry-with-backoff (T020) is for transient
    remote-service errors, not "you haven't started Ollama"; an unreachable
    local server fails fast with an actionable message instead.
    """
    if not texts:
        return []

    session = session or requests.Session()
    try:
        response = session.post(
            f"{base_url}{EMBED_PATH}",
            json={"model": EMBED_MODEL, "input": texts},
            timeout=60,
        )
    except requests.RequestException as exc:
        raise OllamaUnavailableError(
            f"Could not reach local Ollama at {base_url}{EMBED_PATH}: {exc}. "
            f"Is `ollama serve` running with `{EMBED_MODEL}` pulled "
            f"(`ollama pull {EMBED_MODEL}`)?"
        ) from exc

    if not response.ok:
        raise OllamaUnavailableError(
            f"Ollama embeddings request failed ({response.status_code}): {response.text}"
        )

    body = response.json()
    vectors = body.get("embeddings")
    if vectors is None or len(vectors) != len(texts):
        raise OllamaUnavailableError(f"Unexpected Ollama embeddings response shape: {body!r}")
    return vectors
