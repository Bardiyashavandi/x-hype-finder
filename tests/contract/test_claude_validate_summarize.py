"""Contract test for the Claude Validate Summarize client (tasks.md T008,
contracts/pipeline-stages.md § Validate Summarize).

Verifies request shape (structured tool-call forcing, deterministic signals
present in the prompt), successful parsing into `ValidationSummarizeResult`,
cost reporting, and retry-then-error behavior on persistent failure — all
against a mocked Anthropic client, never a live API call. Mirrors
tests/contract/test_claude_summarize.py's structure.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from src.agent import validate_summarize as validate_summarize_module
from src.agent.validate_summarize import (
    VALIDATE_SUMMARIZE_TOOL_NAME,
    ValidateSummarizeError,
    ValidateSummarizeInput,
    summarize_validation_theme,
)

MODEL = "claude-sonnet-5"
API_KEY = "test-key"


def _input(**overrides) -> ValidateSummarizeInput:
    defaults = dict(
        problem_phrases=["can't find sublet", "sublet is a nightmare"],
        post_texts=["Can't find a sublet anywhere", "Sublet search is a nightmare here"],
        cluster_post_count=14,
        distinct_author_count=9,
    )
    defaults.update(overrides)
    return ValidateSummarizeInput(**defaults)


def _tool_use_block(**input_overrides):
    tool_input = {
        "summary": "People are struggling to find short-term sublets in a new city.",
        "representative_ask": "I just need a place for 3 months and no one lists that short.",
        "recurrence_signal": "recurring",
    }
    tool_input.update(input_overrides)
    return SimpleNamespace(type="tool_use", name=VALIDATE_SUMMARIZE_TOOL_NAME, input=tool_input)


def _response(*, content=None, input_tokens=500, output_tokens=120):
    return SimpleNamespace(
        content=content if content is not None else [_tool_use_block()],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _client_with_response(response):
    client = MagicMock()
    client.messages.create.return_value = response
    return client


def test_request_shape_forces_the_validate_summarize_tool_and_includes_signals():
    client = _client_with_response(_response())

    summarize_validation_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    client.messages.create.assert_called_once()
    _, kwargs = client.messages.create.call_args
    assert kwargs["model"] == MODEL
    assert kwargs["tool_choice"] == {"type": "tool", "name": VALIDATE_SUMMARIZE_TOOL_NAME}
    assert kwargs["tools"][0]["name"] == VALIDATE_SUMMARIZE_TOOL_NAME
    assert kwargs["tools"][0]["strict"] is True
    prompt = kwargs["messages"][0]["content"]
    assert "can't find sublet" in prompt
    assert "14" in prompt
    assert "9" in prompt
    assert "no XML tags" in prompt


def test_prompt_frames_want_frustration_not_trending():
    """Locks in the research.md §5 prompt reframing: this is not
    summarize.py's 'why is this trending' framing."""
    client = _client_with_response(_response())

    summarize_validation_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "trending" not in prompt.lower() or "not a 'why is this trending'" in prompt.lower()
    assert "want" in prompt.lower() or "frustrat" in prompt.lower()


def test_successful_response_parses_into_validation_summarize_result():
    client = _client_with_response(_response())

    result = summarize_validation_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert result.summary == "People are struggling to find short-term sublets in a new city."
    assert result.representative_ask == (
        "I just need a place for 3 months and no one lists that short."
    )
    assert result.recurrence_signal == "recurring"


def test_reports_token_spend_to_cost_tracker(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        validate_summarize_module,
        "record_claude_usage",
        lambda model, input_tokens, output_tokens: recorded.append(
            (model, input_tokens, output_tokens)
        ),
    )
    client = _client_with_response(_response(input_tokens=321, output_tokens=45))

    summarize_validation_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert recorded == [(MODEL, 321, 45)]


def test_missing_tool_use_block_raises_validate_summarize_error():
    client = _client_with_response(_response(content=[SimpleNamespace(type="text", text="oops")]))

    with pytest.raises(ValidateSummarizeError):
        summarize_validation_theme(_input(), api_key=API_KEY, model=MODEL, client=client)


def test_invalid_recurrence_signal_raises_validate_summarize_error():
    client = _client_with_response(
        _response(content=[_tool_use_block(recurrence_signal="definitely-a-trend")])
    )

    with pytest.raises(ValidateSummarizeError):
        summarize_validation_theme(_input(), api_key=API_KEY, model=MODEL, client=client)


def test_missing_required_field_raises_validate_summarize_error():
    block = _tool_use_block()
    del block.input["representative_ask"]
    client = _client_with_response(_response(content=[block]))

    with pytest.raises(ValidateSummarizeError):
        summarize_validation_theme(_input(), api_key=API_KEY, model=MODEL, client=client)


def test_persistent_connection_error_retries_then_raises_validate_summarize_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = MagicMock()
    client.messages.create.side_effect = anthropic.APIConnectionError(request=request)

    with pytest.raises(ValidateSummarizeError):
        summarize_validation_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    # Retried up to max_attempts (3) before giving up, per T020's retry-with-backoff.
    assert client.messages.create.call_count == 3


def test_persistent_rate_limit_retries_then_raises_validate_summarize_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request)
    client = MagicMock()
    client.messages.create.side_effect = anthropic.RateLimitError(
        "rate limited", response=response, body=None
    )

    with pytest.raises(ValidateSummarizeError):
        summarize_validation_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert client.messages.create.call_count == 3


def test_transient_error_then_success_does_not_surface_as_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = MagicMock()
    client.messages.create.side_effect = [
        anthropic.APIConnectionError(request=request),
        _response(),
    ]

    result = summarize_validation_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert result.recurrence_signal == "recurring"
    assert client.messages.create.call_count == 2


def test_default_client_construction_sets_an_explicit_request_timeout(monkeypatch):
    """Only exercised when `summarize_validation_theme` builds its own client
    (no `client=` override) — mirrors test_claude_summarize.py's equivalent
    test for the stuck-call-without-timeout failure mode."""
    captured_kwargs = {}

    class _FakeAnthropicClient:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)
            self.messages = SimpleNamespace(create=lambda **_: _response())

    monkeypatch.setattr(validate_summarize_module.anthropic, "Anthropic", _FakeAnthropicClient)

    summarize_validation_theme(_input(), api_key=API_KEY, model=MODEL)

    assert captured_kwargs["api_key"] == API_KEY
    timeout = captured_kwargs["timeout"]
    assert timeout.connect == 10.0
    assert timeout.read == 60.0
