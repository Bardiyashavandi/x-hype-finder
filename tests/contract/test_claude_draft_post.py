"""Contract test for the Claude Draft Post client (tasks.md T056,
contracts/pipeline-stages.md § Draft Post, contracts/external-integrations.md § LLM).

Verifies request shape (structured tool-call forcing, 280-char schema
constraint), successful parsing into `DraftPostResult`, cost reporting,
retry-then-error behavior on persistent connection failure, and — the focus
of this file — the length-correction loop: an over-length draft_text must be
fed back to Claude as a tool_result error with the real conversation so far,
giving it a bounded number of chances to shorten itself, rather than either
(a) silently accepting an over-length post or (b) discarding the theme's
draft after a single miss with no signal. All against a mocked Anthropic
client, never a live API call.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import httpx
import pytest

from src.agent import draft_post as draft_post_module
from src.agent.draft_post import (
    DRAFT_POST_TOOL_NAME,
    DraftPostError,
    DraftPostInput,
    generate_draft_post,
)

MODEL = "claude-sonnet-5"
API_KEY = "test-key"


def _input(**overrides) -> DraftPostInput:
    defaults = dict(
        topic_name="AI agents",
        theme_summary="Developers are discussing a new agent framework release.",
        theme_rationale="Cluster of 30 posts, 4x baseline, 15 distinct accounts.",
        example_post_texts=["This new agent framework is great", "Finally a good agent SDK"],
    )
    defaults.update(overrides)
    return DraftPostInput(**defaults)


def _tool_use_block(*, draft_text: str, tool_use_id: str = "toolu_1"):
    return SimpleNamespace(
        type="tool_use",
        id=tool_use_id,
        name=DRAFT_POST_TOOL_NAME,
        input={"draft_text": draft_text},
    )


def _response(*, content=None, input_tokens=400, output_tokens=80):
    return SimpleNamespace(
        content=content if content is not None else [_tool_use_block(draft_text="A short post.")],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


def _client_with_response(response):
    client = MagicMock()
    client.messages.create.return_value = response
    return client


def test_request_shape_forces_the_draft_post_tool_and_constrains_length():
    client = _client_with_response(_response())

    generate_draft_post(_input(), api_key=API_KEY, model=MODEL, client=client)

    client.messages.create.assert_called_once()
    _, kwargs = client.messages.create.call_args
    assert kwargs["model"] == MODEL
    assert kwargs["tool_choice"] == {"type": "tool", "name": DRAFT_POST_TOOL_NAME}
    assert kwargs["tools"][0]["name"] == DRAFT_POST_TOOL_NAME
    assert kwargs["tools"][0]["strict"] is True
    assert kwargs["tools"][0]["input_schema"]["properties"]["draft_text"]["maxLength"] == 280
    prompt = kwargs["messages"][0]["content"]
    assert "AI agents" in prompt
    assert "280 characters or fewer" in prompt


def test_voice_guide_is_loaded_from_its_standalone_file_not_hardcoded():
    """The draft_text schema description's tone/grounding constraints must
    come from prompts/voice_guide.md at call time, not a copy hardcoded in
    draft_post.py — this asserts against the loaded file content itself so
    an edit to the guide never requires a matching test edit."""
    voice_guide_text = draft_post_module.VOICE_GUIDE_PATH.read_text(encoding="utf-8").strip()
    client = _client_with_response(_response())

    generate_draft_post(_input(), api_key=API_KEY, model=MODEL, client=client)

    _, kwargs = client.messages.create.call_args
    schema_description = kwargs["tools"][0]["input_schema"]["properties"]["draft_text"][
        "description"
    ]
    assert voice_guide_text in schema_description


def test_successful_response_parses_into_draft_post_result():
    client = _client_with_response(_response(content=[_tool_use_block(draft_text="Solid post.")]))

    result = generate_draft_post(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert result.draft_text == "Solid post."


def test_reports_token_spend_to_cost_tracker(monkeypatch):
    recorded = []
    monkeypatch.setattr(
        draft_post_module,
        "record_claude_usage",
        lambda model, input_tokens, output_tokens: recorded.append(
            (model, input_tokens, output_tokens)
        ),
    )
    client = _client_with_response(_response(input_tokens=210, output_tokens=30))

    generate_draft_post(_input(), api_key=API_KEY, model=MODEL, client=client)

    assert recorded == [(MODEL, 210, 30)]


def test_missing_tool_use_block_raises_draft_post_error():
    client = _client_with_response(_response(content=[SimpleNamespace(type="text", text="oops")]))

    with pytest.raises(DraftPostError):
        generate_draft_post(_input(), api_key=API_KEY, model=MODEL, client=client)


def test_empty_draft_text_raises_draft_post_error():
    client = _client_with_response(_response(content=[_tool_use_block(draft_text="   ")]))

    with pytest.raises(DraftPostError):
        generate_draft_post(_input(), api_key=API_KEY, model=MODEL, client=client)


def test_malformed_tool_input_raises_draft_post_error():
    block = _tool_use_block(draft_text="whatever")
    del block.input["draft_text"]
    client = _client_with_response(_response(content=[block]))

    with pytest.raises(DraftPostError):
        generate_draft_post(_input(), api_key=API_KEY, model=MODEL, client=client)


def test_persistent_connection_error_retries_then_raises_draft_post_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    client = MagicMock()
    client.messages.create.side_effect = anthropic.APIConnectionError(request=request)

    with pytest.raises(DraftPostError):
        generate_draft_post(_input(), api_key=API_KEY, model=MODEL, client=client)

    # Retried up to max_attempts (3) before giving up, per T020's retry-with-backoff.
    assert client.messages.create.call_count == 3


class TestLengthCorrectionLoop:
    """The over-length case is the one that broke in production: themes were
    silently losing their draft post because a single over-budget generation
    was treated as terminal. These tests lock in that a first-attempt miss
    is recoverable, and that a persistent miss still fails loudly (raises)
    rather than being accepted as-is or swallowed without a trace.
    """

    def test_over_length_draft_is_corrected_on_retry_and_recovers(self):
        over_length_text = "x" * 300
        compliant_text = "A properly sized post about the new agent framework."
        client = MagicMock()
        client.messages.create.side_effect = [
            _response(content=[_tool_use_block(draft_text=over_length_text, tool_use_id="toolu_1")]),
            _response(content=[_tool_use_block(draft_text=compliant_text, tool_use_id="toolu_2")]),
        ]

        result = generate_draft_post(_input(), api_key=API_KEY, model=MODEL, client=client)

        assert result.draft_text == compliant_text
        assert client.messages.create.call_count == 2

        # The second call must be a real continuation of the conversation —
        # the model's own over-length attempt plus a tool_result telling it
        # exactly how far over it was — not an independent do-over.
        second_call_messages = client.messages.create.call_args_list[1].kwargs["messages"]
        assert len(second_call_messages) == 3
        assert second_call_messages[0]["role"] == "user"
        assistant_turn = second_call_messages[1]
        assert assistant_turn["role"] == "assistant"
        assert assistant_turn["content"][0].input["draft_text"] == over_length_text

        correction_turn = second_call_messages[2]
        assert correction_turn["role"] == "user"
        tool_result = correction_turn["content"][0]
        assert tool_result["type"] == "tool_result"
        assert tool_result["tool_use_id"] == "toolu_1"
        assert tool_result["is_error"] is True
        assert "300 characters" in tool_result["content"]
        assert "20 over the 280 limit" in tool_result["content"]

    def test_reports_cost_for_every_attempt_in_the_correction_loop(self, monkeypatch):
        recorded = []
        monkeypatch.setattr(
            draft_post_module,
            "record_claude_usage",
            lambda model, input_tokens, output_tokens: recorded.append(
                (model, input_tokens, output_tokens)
            ),
        )
        client = MagicMock()
        client.messages.create.side_effect = [
            _response(
                content=[_tool_use_block(draft_text="x" * 300)],
                input_tokens=100,
                output_tokens=50,
            ),
            _response(content=[_tool_use_block(draft_text="Fits fine.")], input_tokens=150, output_tokens=20),
        ]

        generate_draft_post(_input(), api_key=API_KEY, model=MODEL, client=client)

        assert recorded == [(MODEL, 100, 50), (MODEL, 150, 20)]

    def test_still_over_length_after_all_correction_attempts_raises_and_is_not_dropped_silently(self):
        """Failure must be loud (DraftPostError raised with the final overage
        in its message) so the orchestrator's except-block explicitly logs
        and skips the theme's draft — as opposed to generate_draft_post ever
        returning an over-length DraftPostResult or None, which would let
        the theme's missing draft go unnoticed.
        """
        client = MagicMock()
        client.messages.create.side_effect = [
            _response(content=[_tool_use_block(draft_text="x" * 300, tool_use_id="toolu_1")]),
            _response(content=[_tool_use_block(draft_text="y" * 320, tool_use_id="toolu_2")]),
            _response(content=[_tool_use_block(draft_text="z" * 290, tool_use_id="toolu_3")]),
        ]

        with pytest.raises(DraftPostError) as exc_info:
            generate_draft_post(_input(), api_key=API_KEY, model=MODEL, client=client)

        # First attempt + _MAX_LENGTH_CORRECTION_ATTEMPTS (2) retries = 3 total calls.
        assert client.messages.create.call_count == 3
        assert "290" in str(exc_info.value)

    def test_correction_attempts_are_bounded_not_unlimited(self):
        """Guards against a regression where the loop retries forever on a
        persistently over-length draft instead of giving up after a fixed
        budget."""
        client = MagicMock()
        client.messages.create.side_effect = [
            _response(content=[_tool_use_block(draft_text="x" * (281 + i), tool_use_id=f"toolu_{i}")])
            for i in range(10)
        ]

        with pytest.raises(DraftPostError):
            generate_draft_post(_input(), api_key=API_KEY, model=MODEL, client=client)

        assert client.messages.create.call_count == 3
