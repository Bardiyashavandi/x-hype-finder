"""Contract test for the Claude Validate Synthesize client
(src/agent/validate_synthesize.py) — the run-level executive-summary/verdict
step over every theme Validate Summarize produced (spec.md §5.3, §7 of
specs/002-idea-validation-mode).

Verifies request shape (structured tool-call forcing, theme content + signal
numbers present in the prompt), successful parsing into
`ValidationVerdictResult`, cost reporting, grounding-discipline language in
the prompt/schema, and retry-then-error behavior on persistent failure — all
against a mocked Anthropic client, never a live API call. Mirrors
tests/contract/test_claude_validate_summarize.py's structure.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from src.agent import validate_synthesize as validate_synthesize_module
from src.agent.validate_summarize import ValidationTheme
from src.agent.validate_synthesize import (
    VALIDATE_SYNTHESIZE_TOOL_NAME,
    ValidateSynthesizeError,
    ValidateSynthesizeInput,
    synthesize_validation_verdict,
)

MODEL = "claude-sonnet-5"
API_KEY = "test-key"


def _theme(**overrides) -> ValidationTheme:
    defaults = dict(
        summary="People struggle to find short-term sublets when moving to a new city.",
        representative_ask="I just need a place for a few months, not a full year lease.",
        recurrence_signal="recurring",
        cluster_post_count=3,
        distinct_author_count=3,
        example_post_texts=["Can't find a sublet anywhere in this city"],
    )
    defaults.update(overrides)
    return ValidationTheme(**defaults)


def _input(**overrides) -> ValidateSynthesizeInput:
    defaults = dict(
        problem_phrases=["can't find sublet", "sublet is a nightmare"],
        themes=[_theme()],
        total_relevant_count=3,
        distinct_author_count=3,
        posts_last_24h=1,
        posts_last_7d=3,
    )
    defaults.update(overrides)
    return ValidateSynthesizeInput(**defaults)


def _tool_use_block(**input_overrides):
    tool_input = {
        "verdict": (
            "There is real, recurring frustration around finding short-term sublets, "
            "concentrated in a single strong theme with three distinct authors. No "
            "competitor or existing solution is described in the evidence. Worth pursuing "
            "further given the concentrated signal."
        ),
    }
    tool_input.update(input_overrides)
    return SimpleNamespace(type="tool_use", name=VALIDATE_SYNTHESIZE_TOOL_NAME, input=tool_input)


def _response(*, content=None, input_tokens=500, output_tokens=120):
    return SimpleNamespace(
        content=content if content is not None else [_tool_use_block()],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _client_with_response(response):
    client = MagicMock()
    client.messages.create.return_value = response
    return client


def test_request_shape_forces_the_validate_synthesize_tool_and_includes_theme_content():
    client = _client_with_response(_response())

    synthesize_validation_verdict(_input(), api_key=API_KEY, model=MODEL, client=client)

    client.messages.create.assert_called_once()
    _, kwargs = client.messages.create.call_args
    assert kwargs["model"] == MODEL
    assert kwargs["tool_choice"] == {"type": "tool", "name": VALIDATE_SYNTHESIZE_TOOL_NAME}
    assert kwargs["tools"][0]["name"] == VALIDATE_SYNTHESIZE_TOOL_NAME
    assert kwargs["tools"][0]["strict"] is True
    prompt = kwargs["messages"][0]["content"]
    assert "can't find sublet" in prompt
    assert "short-term sublets" in prompt  # theme summary
    assert "recurring" in prompt  # theme recurrence_signal
    assert "total_relevant_count: 3" in prompt
    assert "posts_last_24h: 1" in prompt


def test_multiple_themes_all_appear_in_the_prompt():
    client = _client_with_response(_response())
    themes = [
        _theme(summary="Theme one summary", recurrence_signal="isolated", cluster_post_count=1),
        _theme(summary="Theme two summary", recurrence_signal="emerging", cluster_post_count=2),
    ]

    synthesize_validation_verdict(
        _input(themes=themes), api_key=API_KEY, model=MODEL, client=client
    )

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Theme one summary" in prompt
    assert "Theme two summary" in prompt


def test_grounding_discipline_language_is_present_in_schema_and_prompt():
    """Locks in point 3 of the feature request: the prompt/schema must
    explicitly forbid inventing competitors or evidence beyond what the
    themes actually contain, and must not default to an optimistic
    recommendation when the evidence is thin."""
    client = _client_with_response(_response())

    synthesize_validation_verdict(_input(), api_key=API_KEY, model=MODEL, client=client)

    _, kwargs = client.messages.create.call_args
    schema_description = kwargs["tools"][0]["input_schema"]["properties"]["verdict"]["description"]
    assert "ONLY if a theme actually describes one" in schema_description
    assert "do not speculate" in schema_description
    assert "do not oversell" in schema_description

    prompt = kwargs["messages"][0]["content"]
    assert "Do not invent" in prompt
    assert "don't hedge toward a" in prompt


def test_successful_response_parses_into_validation_verdict_result():
    client = _client_with_response(_response())

    result = synthesize_validation_verdict(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert "recurring frustration" in result.verdict


def test_reports_token_spend_to_cost_tracker(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        validate_synthesize_module,
        "record_claude_usage",
        lambda model, input_tokens, output_tokens: recorded.append(
            (model, input_tokens, output_tokens)
        ),
    )
    client = _client_with_response(_response(input_tokens=321, output_tokens=45))

    synthesize_validation_verdict(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert recorded == [(MODEL, 321, 45)]


def test_missing_tool_use_block_raises_validate_synthesize_error():
    client = _client_with_response(_response(content=[SimpleNamespace(type="text", text="oops")]))

    with pytest.raises(ValidateSynthesizeError):
        synthesize_validation_verdict(_input(), api_key=API_KEY, model=MODEL, client=client)


def test_missing_required_field_raises_validate_synthesize_error():
    block = _tool_use_block()
    del block.input["verdict"]
    client = _client_with_response(_response(content=[block]))

    with pytest.raises(ValidateSynthesizeError):
        synthesize_validation_verdict(_input(), api_key=API_KEY, model=MODEL, client=client)


def test_empty_verdict_raises_validate_synthesize_error():
    client = _client_with_response(_response(content=[_tool_use_block(verdict="   ")]))

    with pytest.raises(ValidateSynthesizeError):
        synthesize_validation_verdict(_input(), api_key=API_KEY, model=MODEL, client=client)


def test_persistent_connection_error_retries_then_raises_validate_synthesize_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = MagicMock()
    client.messages.create.side_effect = anthropic.APIConnectionError(request=request)

    with pytest.raises(ValidateSynthesizeError):
        synthesize_validation_verdict(_input(), api_key=API_KEY, model=MODEL, client=client)

    # Retried up to max_attempts (3) before giving up, per T020's retry-with-backoff.
    assert client.messages.create.call_count == 3


def test_persistent_rate_limit_retries_then_raises_validate_synthesize_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(429, request=request)
    client = MagicMock()
    client.messages.create.side_effect = anthropic.RateLimitError(
        "rate limited", response=response, body=None
    )

    with pytest.raises(ValidateSynthesizeError):
        synthesize_validation_verdict(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert client.messages.create.call_count == 3


def test_transient_error_then_success_does_not_surface_as_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = MagicMock()
    client.messages.create.side_effect = [
        anthropic.APIConnectionError(request=request),
        _response(),
    ]

    result = synthesize_validation_verdict(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert "recurring frustration" in result.verdict
    assert client.messages.create.call_count == 2


def test_default_client_construction_sets_an_explicit_request_timeout(monkeypatch):
    """Only exercised when `synthesize_validation_verdict` builds its own
    client (no `client=` override) — mirrors the equivalent test in
    test_claude_validate_summarize.py for the stuck-call-without-timeout
    failure mode."""
    captured_kwargs = {}

    class _FakeAnthropicClient:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)
            self.messages = SimpleNamespace(create=lambda **_: _response())

    monkeypatch.setattr(validate_synthesize_module.anthropic, "Anthropic", _FakeAnthropicClient)

    synthesize_validation_verdict(_input(), api_key=API_KEY, model=MODEL)

    assert captured_kwargs["api_key"] == API_KEY
    timeout = captured_kwargs["timeout"]
    assert timeout.connect == 10.0
    assert timeout.read == 60.0
