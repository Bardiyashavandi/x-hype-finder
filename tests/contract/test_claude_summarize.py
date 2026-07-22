"""Contract test for the Claude Summarize client (tasks.md T030,
contracts/pipeline-stages.md § Summarize, contracts/external-integrations.md § LLM).

Verifies request shape (structured tool-call forcing, deterministic signals
present in the prompt), successful parsing into `SummarizeResult`, cost
reporting, and retry-then-error behavior on persistent failure — all against
a mocked Anthropic client, never a live API call.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from src.agent import summarize as summarize_module
from src.agent.summarize import (
    SUMMARIZE_TOOL_NAME,
    SummarizeError,
    SummarizeInput,
    summarize_theme,
)

MODEL = "claude-sonnet-5"
API_KEY = "test-key"


def _input(**overrides) -> SummarizeInput:
    defaults = dict(
        topic_name="AAPL",
        post_texts=["Big news about AAPL today", "AAPL is trending hard"],
        spike_ratio=4.2,
        cluster_post_count=41,
        filter_survival_rate=0.75,
        account_diversity_count=12,
    )
    defaults.update(overrides)
    return SummarizeInput(**defaults)


def _tool_use_block(**input_overrides):
    tool_input = {
        "summary": "AAPL is seeing a surge of bullish chatter after earnings.",
        "rationale": "Cluster of 41 posts, 4.2x baseline, 12 distinct accounts.",
        "confidence_score": 82,
    }
    tool_input.update(input_overrides)
    return SimpleNamespace(type="tool_use", name=SUMMARIZE_TOOL_NAME, input=tool_input)


def _response(*, content=None, input_tokens=500, output_tokens=120):
    return SimpleNamespace(
        content=content if content is not None else [_tool_use_block()],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _client_with_response(response):
    client = MagicMock()
    client.messages.create.return_value = response
    return client


def test_request_shape_forces_the_summarize_tool_and_includes_signals():
    client = _client_with_response(_response())

    summarize_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    client.messages.create.assert_called_once()
    _, kwargs = client.messages.create.call_args
    assert kwargs["model"] == MODEL
    assert kwargs["tool_choice"] == {"type": "tool", "name": SUMMARIZE_TOOL_NAME}
    assert kwargs["tools"][0]["name"] == SUMMARIZE_TOOL_NAME
    prompt = kwargs["messages"][0]["content"]
    assert "4.20x baseline" in prompt
    assert "41" in prompt
    assert "75%" in prompt
    assert "12" in prompt


def test_successful_response_parses_into_summarize_result():
    client = _client_with_response(_response())

    result = summarize_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert result.summary == "AAPL is seeing a surge of bullish chatter after earnings."
    assert result.rationale == "Cluster of 41 posts, 4.2x baseline, 12 distinct accounts."
    assert result.confidence_score == 82


def test_reports_token_spend_to_cost_tracker(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        summarize_module,
        "record_claude_usage",
        lambda model, input_tokens, output_tokens: recorded.append(
            (model, input_tokens, output_tokens)
        ),
    )
    client = _client_with_response(_response(input_tokens=321, output_tokens=45))

    summarize_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert recorded == [(MODEL, 321, 45)]


def test_observation_period_with_no_spike_ratio_is_grounded_as_na():
    client = _client_with_response(_response())

    summarize_theme(_input(spike_ratio=None), api_key=API_KEY, model=MODEL, client=client)

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "observation period" in prompt


def test_missing_tool_use_block_raises_summarize_error():
    client = _client_with_response(_response(content=[SimpleNamespace(type="text", text="oops")]))

    with pytest.raises(SummarizeError):
        summarize_theme(_input(), api_key=API_KEY, model=MODEL, client=client)


def test_confidence_score_out_of_range_raises_summarize_error():
    client = _client_with_response(_response(content=[_tool_use_block(confidence_score=150)]))

    with pytest.raises(SummarizeError):
        summarize_theme(_input(), api_key=API_KEY, model=MODEL, client=client)


def test_missing_required_field_raises_summarize_error():
    block = _tool_use_block()
    del block.input["rationale"]
    client = _client_with_response(_response(content=[block]))

    with pytest.raises(SummarizeError):
        summarize_theme(_input(), api_key=API_KEY, model=MODEL, client=client)


def test_persistent_connection_error_retries_then_raises_summarize_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = MagicMock()
    client.messages.create.side_effect = anthropic.APIConnectionError(request=request)

    with pytest.raises(SummarizeError):
        summarize_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    # Retried up to max_attempts (3) before giving up, per T020's retry-with-backoff.
    assert client.messages.create.call_count == 3


def test_persistent_rate_limit_retries_then_raises_summarize_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request)
    client = MagicMock()
    client.messages.create.side_effect = anthropic.RateLimitError(
        "rate limited", response=response, body=None
    )

    with pytest.raises(SummarizeError):
        summarize_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert client.messages.create.call_count == 3


def test_transient_error_then_success_does_not_surface_as_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = MagicMock()
    client.messages.create.side_effect = [
        anthropic.APIConnectionError(request=request),
        _response(),
    ]

    result = summarize_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert result.confidence_score == 82
    assert client.messages.create.call_count == 2
