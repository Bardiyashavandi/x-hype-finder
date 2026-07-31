"""Voyage AI embeddings client (src/pipeline/embedding_provider.py's
alternative to the local Ollama client, src/pipeline/embeddings.py).

For users without a local Ollama install: a hosted embeddings API selected
via `EMBEDDING_PROVIDER=voyage` (contracts/external-integrations.md §
Embeddings). Mirrors the Ollama client's shape — no retry-with-backoff, since
an auth/config problem here is a setup fault, not a transient remote error —
but requires a `VOYAGE_API_KEY` and talks to Voyage AI's hosted REST API
instead of a local server.
"""

from __future__ import annotations

import requests

VOYAGE_BASE_URL = "https://api.voyageai.com/v1"
EMBED_PATH = "/embeddings"
EMBED_MODEL = "voyage-4-lite"


class VoyageUnavailableError(RuntimeError):
    """Raised when the Voyage AI API can't be reached or returns something unusable."""


def get_embeddings(
    texts: list[str],
    *,
    api_key: str,
    base_url: str = VOYAGE_BASE_URL,
    session: requests.Session | None = None,
) -> list[list[float]]:
    """Return one embedding vector per input text, in the same order.

    Deliberately does not retry, matching src/pipeline/embeddings.py — an
    unreachable API or bad key fails fast with an actionable message rather
    than masking a setup problem behind retries.
    """
    if not texts:
        return []

    session = session or requests.Session()
    try:
        response = session.post(
            f"{base_url}{EMBED_PATH}",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": EMBED_MODEL, "input": texts},
            timeout=60,
        )
    except requests.RequestException as exc:
        raise VoyageUnavailableError(
            f"Could not reach Voyage AI at {base_url}{EMBED_PATH}: {exc}. "
            "Check network connectivity and that VOYAGE_API_KEY is set correctly."
        ) from exc

    if not response.ok:
        raise VoyageUnavailableError(
            f"Voyage AI embeddings request failed ({response.status_code}): {response.text}"
        )

    body = response.json()
    data = body.get("data")
    if data is None or len(data) != len(texts):
        raise VoyageUnavailableError(f"Unexpected Voyage AI embeddings response shape: {body!r}")

    try:
        ordered = sorted(data, key=lambda item: item["index"])
        vectors = [item["embedding"] for item in ordered]
    except (KeyError, TypeError) as exc:
        raise VoyageUnavailableError(
            f"Unexpected Voyage AI embeddings response shape: {body!r}"
        ) from exc

    return vectors
