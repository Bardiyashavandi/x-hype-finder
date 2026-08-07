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
    assert kwargs["tools"][0]["strict"] is True
    prompt = kwargs["messages"][0]["content"]
    assert "4.20x baseline" in prompt
    assert "41" in prompt
    assert "75%" in prompt
    assert "12" in prompt
    assert "no XML tags" in prompt


def test_confidence_score_calibration_guidance_is_present():
    """Locks in a real observed miscalibration fix: weak-signal themes
    (single post/author, no spike_ratio) were scoring 4-8 despite their own
    rationale concluding 'not a genuine trend' — the model was hedging
    toward a moderate score instead of the floor. Both the tool schema and
    the prompt must anchor low-signal cases to 0-5 and state explicitly
    that this isn't a hedge, so a future edit can't silently drop it."""
    client = _client_with_response(_response())

    summarize_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    _, kwargs = client.messages.create.call_args
    schema_description = kwargs["tools"][0]["input_schema"]["properties"]["confidence_score"][
        "description"
    ]
    assert "0-5" in schema_description
    assert "not a hedge" in schema_description
    assert "STRENGTH OF EVIDENCE" in schema_description

    prompt = kwargs["messages"][0]["content"]
    assert "0-5" in prompt
    assert "confidence in your reasoning" in prompt


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


def test_leaked_confidence_score_parameter_is_recovered_not_discarded():
    """Simulates the exact artifact observed twice in production: a stray
    legacy-format `</rationale>\\n<parameter name="confidence_score">N`
    fragment leaks into the rationale string, and confidence_score is
    missing from tool_input entirely. The defensive fallback
    (_recover_leaked_confidence_score) must recover a clean rationale plus
    the intended score instead of raising SummarizeError and discarding the
    whole theme."""
    clean_rationale = (
        "This looks like an isolated promotional post about a funding round, not a genuine trend."
    )
    leaked_rationale = clean_rationale + '</rationale>\n<parameter name="confidence_score">8'
    block = SimpleNamespace(
        type="tool_use",
        name=SUMMARIZE_TOOL_NAME,
        input={
            "summary": "A single post about a funding round.",
            "rationale": leaked_rationale,
            # confidence_score deliberately absent — leaked into rationale above,
            # exactly as observed in production.
        },
    )
    client = _client_with_response(_response(content=[block]))

    result = summarize_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert result.confidence_score == 8
    assert result.rationale == clean_rationale
    assert "<parameter" not in result.rationale
    assert "</rationale>" not in result.rationale


def test_leaked_parameter_artifact_is_stripped_even_when_confidence_score_already_present():
    """A second production variant of the same artifact: confidence_score
    IS present and correct in its own field, but Claude *also* appends the
    same trailing `</parameter>\\n<parameter name="confidence_score">N`
    fragment onto rationale regardless. The original fallback only scanned
    for the leak when confidence_score was missing entirely, so this variant
    left the artifact stuck in the persisted rationale (observed for real:
    a `digest show --full` row rendered with the raw tag text in it). The
    fix must strip the artifact from rationale unconditionally, without
    touching the already-correct confidence_score."""
    clean_rationale = (
        "This cluster consists of just one post from one author, with no "
        "evidence of a genuine trending theme — this is an isolated "
        "single-author post."
    )
    leaked_rationale = clean_rationale + '</parameter>\n<parameter name="confidence_score">2'
    block = SimpleNamespace(
        type="tool_use",
        name=SUMMARIZE_TOOL_NAME,
        input={
            "summary": "A single investor/promotional post.",
            "rationale": leaked_rationale,
            "confidence_score": 2,  # already present and correct
        },
    )
    client = _client_with_response(_response(content=[block]))

    result = summarize_theme(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert result.confidence_score == 2
    assert result.rationale == clean_rationale
    assert "<parameter" not in result.rationale
    assert "</parameter>" not in result.rationale


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


def test_default_client_construction_sets_an_explicit_request_timeout(monkeypatch):
    """Without an explicit timeout, a hung call blocks silently forever
    instead of failing into retry_with_backoff (observed live: a `digest
    run` sat with zero output for 55+ minutes on a stuck call before being
    killed manually). Only exercised when `summarize_theme` builds its own
    client (no `client=` override) — every other test in this file passes a
    mock client and never reaches this construction path at all."""
    captured_kwargs = {}

    class _FakeAnthropicClient:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)
            self.messages = SimpleNamespace(create=lambda **_: _response())

    monkeypatch.setattr(summarize_module.anthropic, "Anthropic", _FakeAnthropicClient)

    summarize_theme(_input(), api_key=API_KEY, model=MODEL)

    assert captured_kwargs["api_key"] == API_KEY
    timeout = captured_kwargs["timeout"]
    # Short connect timeout (fail fast if the host is unreachable at all);
    # full 60s read/write/pool timeout (legitimate generations can take tens
    # of seconds) — see _CLAUDE_REQUEST_TIMEOUT in summarize.py.
    assert timeout.connect == 10.0
    assert timeout.read == 60.0
