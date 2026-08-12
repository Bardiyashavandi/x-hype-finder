"""Unit tests for the fetch provider abstraction
(src/pipeline/fetch_provider.py) — selection via FETCH_PROVIDER,
default-to-twitterapis_com, and the *_KEY-required-only-if-selected rule.

Uses an explicit `env` mapping throughout (never the real environment or
`.env`), and never makes a live network call — each provider's own
request/response behavior is covered separately in
tests/contract/test_twitterapi_io.py and tests/contract/test_twitterapis_com.py.
"""

from __future__ import annotations

import functools

import pytest

from src.pipeline import fetch as twitterapi_io_fetch
from src.pipeline import fetch_twitterapis_com as twitterapis_com_fetch
from src.pipeline.fetch_provider import (
    FetchProviderError,
    get_fetch_provider,
    get_fetch_provider_for_query,
)


def test_defaults_to_twitterapis_com_when_unset():
    provider = get_fetch_provider(env={"TWITTERAPIS_COM_KEY": "test-key"})

    assert isinstance(provider, functools.partial)
    assert provider.func is twitterapis_com_fetch.fetch_topic_posts
    assert provider.keywords == {"api_key": "test-key"}


def test_explicit_twitterapi_io_selection():
    provider = get_fetch_provider(
        env={"FETCH_PROVIDER": "twitterapi_io", "TWITTERAPI_IO_KEY": "test-key"}
    )

    assert provider.func is twitterapi_io_fetch.fetch_topic_posts


def test_selection_is_case_insensitive_and_trims_whitespace():
    provider = get_fetch_provider(
        env={"FETCH_PROVIDER": " Twitterapi_Io ", "TWITTERAPI_IO_KEY": "test-key"}
    )

    assert provider.func is twitterapi_io_fetch.fetch_topic_posts


def test_twitterapi_io_selection_without_api_key_raises_clear_error():
    with pytest.raises(FetchProviderError, match="TWITTERAPI_IO_KEY"):
        get_fetch_provider(env={"FETCH_PROVIDER": "twitterapi_io"})


def test_twitterapis_com_selection_without_api_key_raises_clear_error():
    with pytest.raises(FetchProviderError, match="TWITTERAPIS_COM_KEY"):
        get_fetch_provider(env={"FETCH_PROVIDER": "twitterapis_com"})


def test_twitterapis_com_selection_with_api_key_returns_bound_client():
    provider = get_fetch_provider(
        env={"FETCH_PROVIDER": "twitterapis_com", "TWITTERAPIS_COM_KEY": "test-key"}
    )

    assert isinstance(provider, functools.partial)
    assert provider.func is twitterapis_com_fetch.fetch_topic_posts
    assert provider.keywords == {"api_key": "test-key"}


def test_unsupported_provider_raises_clear_error():
    with pytest.raises(FetchProviderError, match="bedrock"):
        get_fetch_provider(env={"FETCH_PROVIDER": "bedrock"})


# --- get_fetch_provider_for_query: the query-string-accepting sibling,
# used by src/cli/idea_validate.py (specs/002-idea-validation-mode) since it
# has no Topic to build a query from. Same FETCH_PROVIDER selection/default/
# required-key rules as get_fetch_provider above, just bound to each
# module's `fetch_posts_for_query` instead of `fetch_topic_posts`.


def test_for_query_defaults_to_twitterapis_com_when_unset():
    provider = get_fetch_provider_for_query(env={"TWITTERAPIS_COM_KEY": "test-key"})

    assert isinstance(provider, functools.partial)
    assert provider.func is twitterapis_com_fetch.fetch_posts_for_query
    assert provider.keywords == {"api_key": "test-key"}


def test_for_query_explicit_twitterapi_io_selection():
    provider = get_fetch_provider_for_query(
        env={"FETCH_PROVIDER": "twitterapi_io", "TWITTERAPI_IO_KEY": "test-key"}
    )

    assert provider.func is twitterapi_io_fetch.fetch_posts_for_query
    assert provider.keywords == {"api_key": "test-key"}


def test_for_query_selection_is_case_insensitive_and_trims_whitespace():
    provider = get_fetch_provider_for_query(
        env={"FETCH_PROVIDER": " Twitterapi_Io ", "TWITTERAPI_IO_KEY": "test-key"}
    )

    assert provider.func is twitterapi_io_fetch.fetch_posts_for_query


def test_for_query_twitterapi_io_selection_without_api_key_raises_clear_error():
    with pytest.raises(FetchProviderError, match="TWITTERAPI_IO_KEY"):
        get_fetch_provider_for_query(env={"FETCH_PROVIDER": "twitterapi_io"})


def test_for_query_twitterapis_com_selection_without_api_key_raises_clear_error():
    with pytest.raises(FetchProviderError, match="TWITTERAPIS_COM_KEY"):
        get_fetch_provider_for_query(env={"FETCH_PROVIDER": "twitterapis_com"})


def test_for_query_unsupported_provider_raises_clear_error():
    with pytest.raises(FetchProviderError, match="bedrock"):
        get_fetch_provider_for_query(env={"FETCH_PROVIDER": "bedrock"})
