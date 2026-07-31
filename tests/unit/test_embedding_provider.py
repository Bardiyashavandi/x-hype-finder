"""Unit tests for the embedding provider abstraction
(src/pipeline/embedding_provider.py) — selection via EMBEDDING_PROVIDER,
default-to-ollama, and the VOYAGE_API_KEY-required-only-if-selected rule.

Uses an explicit `env` mapping throughout (never the real environment or
`.env`), and never makes a live network call — Voyage's own request/response
behavior is covered separately in tests/contract/test_voyage_embeddings.py.
"""

from __future__ import annotations

import functools

import pytest

from src.pipeline import embeddings as ollama_embeddings
from src.pipeline import embeddings_voyage as voyage_embeddings
from src.pipeline.embedding_provider import EmbeddingProviderError, get_embedding_provider


def test_defaults_to_ollama_when_unset():
    provider = get_embedding_provider(env={})

    assert provider is ollama_embeddings.get_embeddings


def test_explicit_ollama_selection():
    provider = get_embedding_provider(env={"EMBEDDING_PROVIDER": "ollama"})

    assert provider is ollama_embeddings.get_embeddings


def test_selection_is_case_insensitive_and_trims_whitespace():
    provider = get_embedding_provider(env={"EMBEDDING_PROVIDER": " Ollama "})

    assert provider is ollama_embeddings.get_embeddings


def test_voyage_selection_without_api_key_raises_clear_error():
    with pytest.raises(EmbeddingProviderError, match="VOYAGE_API_KEY"):
        get_embedding_provider(env={"EMBEDDING_PROVIDER": "voyage"})


def test_voyage_selection_with_api_key_returns_bound_voyage_client():
    provider = get_embedding_provider(
        env={"EMBEDDING_PROVIDER": "voyage", "VOYAGE_API_KEY": "test-key"}
    )

    assert isinstance(provider, functools.partial)
    assert provider.func is voyage_embeddings.get_embeddings
    assert provider.keywords == {"api_key": "test-key"}


def test_unsupported_provider_raises_clear_error():
    with pytest.raises(EmbeddingProviderError, match="bedrock"):
        get_embedding_provider(env={"EMBEDDING_PROVIDER": "bedrock"})
