"""Claude Draft Post client (tasks.md T056, contracts/pipeline-stages.md §
Draft Post).

Generates `draft_text` for a `DraftPost` from a high-signal Theme (summary +
rationale + example posts) — the second and final LLM-powered stage,
downstream of Summarize/Rank. `confidence_score` is NOT generated here: per
data-model.md's DraftPost entity, it is copied from the Theme at draft time,
not re-invented by this stage.

Model name is read from `src/config.py` (T021), never hardcoded here, so it
can move from `claude-sonnet-5` to `claude-haiku-4-5-20251001` after T059's
week-3 reassessment without touching this module (research.md §3,
/speckit-analyze finding E1). Token spend is reported to the cost tracker
from T022. Mirrors src/agent/summarize.py's structure/conventions.
"""

from __future__ import annotations

from dataclasses import dataclass

import anthropic

from src.utils.cost_tracker import record_claude_usage
from src.utils.retry import retry_with_backoff

DRAFT_POST_TOOL_NAME = "submit_draft_post"

_MAX_EXAMPLE_POSTS_IN_PROMPT = 5
# X's post character limit — the draft must be publishable as-is, with no
# truncation/formatting step between this stage and an autonomous publish.
_MAX_POST_LENGTH = 280
# Extra attempts (beyond the first) to let the model shorten an over-length
# draft with concrete feedback about its own prior output, rather than
# discarding the theme's draft after a single miss (research.md § Draft Post
# length handling).
_MAX_LENGTH_CORRECTION_ATTEMPTS = 2

_TOOL_SCHEMA = {
    "name": DRAFT_POST_TOOL_NAME,
    "strict": True,
    "description": "Submit a ready-to-publish X post drafted from a trending theme.",
    "input_schema": {
        "type": "object",
        "properties": {
            "draft_text": {
                "type": "string",
                "maxLength": _MAX_POST_LENGTH,
                "description": (
                    f"The post text itself, {_MAX_POST_LENGTH} characters or fewer, "
                    "written in a natural, human voice — no hashtag spam, no "
                    "generic hype filler, no fabricated numbers not present in "
                    "the provided summary/rationale/examples. State the trend "
                    "plainly, as a person who follows this topic closely would."
                ),
            },
        },
        "required": ["draft_text"],
        "additionalProperties": False,
    },
}

_RETRYABLE_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


@dataclass(frozen=True)
class DraftPostInput:
    """A high-signal Theme's content (contracts/pipeline-stages.md § Draft Post)."""

    topic_name: str
    theme_summary: str
    theme_rationale: str
    example_post_texts: list[str]


@dataclass(frozen=True)
class DraftPostResult:
    draft_text: str


class DraftPostError(RuntimeError):
    """Raised on persistent Claude failure or a malformed tool response.

    Callers (the orchestrator) should catch this and skip drafting for the
    affected Theme rather than failing the whole run (contracts/
    external-integrations.md § LLM) — the Theme itself still appears in the
    digest either way, only its draft post is missing.
    """


def _build_prompt(data: DraftPostInput) -> str:
    examples = "\n".join(
        f"- {text}" for text in data.example_post_texts[:_MAX_EXAMPLE_POSTS_IN_PROMPT]
    )
    return (
        f"Topic being monitored: {data.topic_name}\n\n"
        f"Theme summary: {data.theme_summary}\n"
        f"Why it's trending: {data.theme_rationale}\n\n"
        f"Representative posts from this theme:\n{examples}\n\n"
        f"Call {DRAFT_POST_TOOL_NAME} with a single ready-to-publish X post "
        f"({_MAX_POST_LENGTH} characters or fewer) about this trend, in plain "
        "prose only — no XML tags, no markup, no `<parameter>`-style text."
    )


@retry_with_backoff(max_attempts=3, base_delay_seconds=0.2, exceptions=_RETRYABLE_ERRORS)
def _call_claude(
    client: anthropic.Anthropic, model: str, messages: list[dict]
) -> anthropic.types.Message:
    return client.messages.create(
        model=model,
        max_tokens=512,
        tools=[_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": DRAFT_POST_TOOL_NAME},
        messages=messages,
    )


def generate_draft_post(
    data: DraftPostInput,
    *,
    api_key: str,
    model: str,
    client: anthropic.Anthropic | None = None,
) -> DraftPostResult:
    """Generate `draft_text` for one Theme via Claude structured tool-call output.

    An over-length draft_text isn't dropped after a single miss: it's fed
    back to Claude as a tool_result error naming the exact overage, giving it
    up to `_MAX_LENGTH_CORRECTION_ATTEMPTS` chances to shorten the same post
    with real context, rather than hoping an independent resample happens to
    fit (research.md § Draft Post length handling).

    Raises `DraftPostError` after retry is exhausted, or if Claude's response
    doesn't carry the expected tool call / a non-empty draft_text within the
    X post length limit after correction attempts are exhausted.
    """
    effective_client = client if client is not None else anthropic.Anthropic(api_key=api_key)
    messages: list[dict] = [{"role": "user", "content": _build_prompt(data)}]

    for attempt in range(_MAX_LENGTH_CORRECTION_ATTEMPTS + 1):
        try:
            response = _call_claude(effective_client, model, messages)
        except anthropic.APIError as exc:
            raise DraftPostError(f"Claude Draft Post request failed: {exc}") from exc

        record_claude_usage(model, response.usage.input_tokens, response.usage.output_tokens)

        tool_use = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_use is None or tool_use.name != DRAFT_POST_TOOL_NAME:
            raise DraftPostError(
                f"Claude did not return the expected tool call: {response.content!r}"
            )

        try:
            draft_text = str(tool_use.input["draft_text"])
        except (KeyError, TypeError) as exc:
            raise DraftPostError(f"Malformed Draft Post tool input: {tool_use.input!r}") from exc

        if not draft_text.strip():
            raise DraftPostError("Claude returned an empty draft_text.")

        overflow = len(draft_text) - _MAX_POST_LENGTH
        if overflow <= 0:
            return DraftPostResult(draft_text=draft_text)

        is_last_attempt = attempt == _MAX_LENGTH_CORRECTION_ATTEMPTS
        if is_last_attempt:
            raise DraftPostError(
                f"draft_text still exceeds the {_MAX_POST_LENGTH}-character X post "
                f"limit after {_MAX_LENGTH_CORRECTION_ATTEMPTS} correction attempt(s): "
                f"{len(draft_text)}"
            )

        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use.id,
                        "is_error": True,
                        "content": (
                            f"That draft_text was {len(draft_text)} characters — "
                            f"{overflow} over the {_MAX_POST_LENGTH} limit. Call "
                            f"{DRAFT_POST_TOOL_NAME} again with the same point, "
                            "shortened to fit. Cut words, don't truncate mid-sentence."
                        ),
                    }
                ],
            }
        )

    raise AssertionError("unreachable — loop above always returns or raises")
