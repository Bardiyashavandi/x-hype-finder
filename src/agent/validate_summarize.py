"""Claude Validate Summarize client (tasks.md T013, contracts/pipeline-stages.md
§ Validate Summarize, data-model.md § ValidationTheme, research.md §5).

Idea Validation mode's sole LLM-powered stage — everything upstream (Query
Construction, Fetch, Relevance Filter, Bot/Noise Filter, Signal Strength,
Cluster) stays fully deterministic (Constitution Principle I/II). Mirrors
`src/agent/summarize.py`'s structured-tool-call pattern (grammar-constrained
schema, `retry_with_backoff`, `record_claude_usage` cost tracking,
leaked-parameter recovery), but with a different prompt framing — "what
people want/are frustrated by," not "why is this trending" — and a
`recurrence_signal` field grounded in this mode's own deterministic signals
(`cluster_post_count`, `distinct_author_count`) instead of a nonexistent
`spike_ratio` (research.md §5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import anthropic

from src.utils.cost_tracker import record_claude_usage
from src.utils.retry import retry_with_backoff

VALIDATE_SUMMARIZE_TOOL_NAME = "submit_validation_theme"

_MAX_EXAMPLE_POSTS_IN_PROMPT = 20

_RECURRENCE_SIGNAL_VALUES = ("isolated", "emerging", "recurring")

_TOOL_SCHEMA = {
    "name": VALIDATE_SUMMARIZE_TOOL_NAME,
    # Grammar-constrained generation — guarantees every required field is
    # present with the declared type, same rationale as summarize.py's
    # SUMMARIZE_TOOL_NAME schema (fighting the same leaked-`<parameter>`
    # artifact class of failure — see _recover_leaked_recurrence_signal
    # below for a defensive fallback in case it recurs anyway).
    "strict": True,
    "description": (
        "Submit a plain-language summary of what people want or are frustrated by in this "
        "cluster of posts, the concrete ask/complaint in their own words, and a recurrence "
        "signal grounded in the deterministic cluster signals provided."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": (
                    "Plain-language, one-to-two-sentence statement of the recurring want or "
                    "frustration this cluster represents — not why it's trending."
                ),
            },
            "representative_ask": {
                "type": "string",
                "description": (
                    "The concrete thing people are asking for or complaining about, in "
                    "language close to the posts themselves — a one-line quote a strategist "
                    "could read back to a client, distinct from `summary`."
                ),
            },
            "recurrence_signal": {
                "type": "string",
                "enum": list(_RECURRENCE_SIGNAL_VALUES),
                "description": (
                    "Grounded in cluster_post_count and distinct_author_count provided below — "
                    "never invented from post text alone. 'isolated': essentially one post from "
                    "one author. 'emerging': a handful of posts and/or few distinct authors. "
                    "'recurring': several posts from several distinct authors."
                ),
            },
        },
        "required": ["summary", "representative_ask", "recurrence_signal"],
        "additionalProperties": False,
    },
}

_RETRYABLE_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)

# Same rationale/values as summarize.py's _CLAUDE_REQUEST_TIMEOUT — a hung
# call must fail fast into retry_with_backoff rather than block silently.
_CLAUDE_REQUEST_TIMEOUT = anthropic.Timeout(60.0, connect=10.0)


@dataclass(frozen=True)
class ValidateSummarizeInput:
    """One cluster's post texts + this mode's deterministic context signals
    (contracts/pipeline-stages.md § Validate Summarize)."""

    problem_phrases: list[str]
    post_texts: list[str]
    cluster_post_count: int
    distinct_author_count: int


@dataclass(frozen=True)
class ValidationSummarizeResult:
    """The raw parsed Claude tool-call output — the caller combines this
    with `cluster_post_count`/`distinct_author_count`/curated example texts
    to build the full `ValidationTheme` below."""

    summary: str
    representative_ask: str
    recurrence_signal: str


@dataclass(frozen=True)
class ValidationTheme:
    """One cluster's complete Idea Validation output (data-model.md §
    ValidationTheme) — the Idea Validation analogue of `Theme`
    (`src/models/theme.py`), but never persisted and carrying different
    fields. `distinct_author_count` rides along from the same context
    Validate Summarize was given, so `report/validation_readout.py` can
    order themes without recomputing it."""

    summary: str
    representative_ask: str
    recurrence_signal: str
    cluster_post_count: int
    distinct_author_count: int
    example_post_texts: list[str]


class ValidateSummarizeError(RuntimeError):
    """Raised on persistent Claude failure or a malformed tool response.

    Callers (`src/cli/idea_validate.py`) should catch this and drop the
    affected theme from the readout with a logged note rather than failing
    the whole run (contracts/pipeline-stages.md § Validate Summarize's
    failure mode).
    """


# Same two production-observed leak variants summarize.py's
# _LEAKED_PARAMETER_PATTERN guards against, adapted to this schema's last
# field (recurrence_signal instead of confidence_score).
_LEAKED_PARAMETER_PATTERN = re.compile(r'</\w+>\s*<parameter name="recurrence_signal">\s*(\w+)\s*$')


def _recover_leaked_recurrence_signal(tool_input: dict) -> dict:
    has_recurrence_signal = "recurrence_signal" in tool_input
    cleaned = dict(tool_input)
    for key, value in tool_input.items():
        if not isinstance(value, str):
            continue
        match = _LEAKED_PARAMETER_PATTERN.search(value)
        if match is None:
            continue
        cleaned[key] = value[: match.start()].rstrip()
        if not has_recurrence_signal:
            cleaned["recurrence_signal"] = match.group(1)
            has_recurrence_signal = True
    return cleaned


def _build_prompt(data: ValidateSummarizeInput) -> str:
    examples = "\n".join(f"- {text}" for text in data.post_texts[:_MAX_EXAMPLE_POSTS_IN_PROMPT])
    phrases = ", ".join(f'"{phrase}"' for phrase in data.problem_phrases)
    return (
        f"Problem statement being validated: {phrases}\n\n"
        "Deterministic signals already computed upstream — ground your "
        "recurrence_signal in these, not in the post text alone:\n"
        f"- cluster_post_count (posts in this cluster): {data.cluster_post_count}\n"
        f"- distinct author count in this cluster: {data.distinct_author_count}\n\n"
        f"Posts in this cluster:\n{examples}\n\n"
        f"Call {VALIDATE_SUMMARIZE_TOOL_NAME} with a plain-language summary of what these "
        "people want or are frustrated by, a representative_ask capturing the concrete thing "
        "they're asking for or complaining about in their own words, and a recurrence_signal.\n\n"
        "IMPORTANT — this is not a 'why is this trending' judgment (there is no trend baseline "
        "here, unlike topic-tracking mode); it's a 'do people genuinely want or need this' "
        "judgment. A single post from a single author is 'isolated', not 'recurring' — do not "
        "round up.\n\n"
        "Write plain prose only in every field — no XML tags, no markup, no "
        "`<parameter>`-style text anywhere in summary or representative_ask."
    )


@retry_with_backoff(max_attempts=3, base_delay_seconds=0.2, exceptions=_RETRYABLE_ERRORS)
def _call_claude(client: anthropic.Anthropic, model: str, prompt: str) -> anthropic.types.Message:
    return client.messages.create(
        model=model,
        max_tokens=1024,
        tools=[_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": VALIDATE_SUMMARIZE_TOOL_NAME},
        messages=[{"role": "user", "content": prompt}],
    )


def summarize_validation_theme(
    data: ValidateSummarizeInput,
    *,
    api_key: str,
    model: str,
    client: anthropic.Anthropic | None = None,
) -> ValidationSummarizeResult:
    """Summarize one Theme candidate for Idea Validation mode via Claude
    structured tool-call output.

    Raises `ValidateSummarizeError` after retry is exhausted, or if Claude's
    response doesn't carry the expected tool call / a valid
    `recurrence_signal`.
    """
    effective_client = (
        client
        if client is not None
        else anthropic.Anthropic(api_key=api_key, timeout=_CLAUDE_REQUEST_TIMEOUT)
    )
    prompt = _build_prompt(data)

    try:
        response = _call_claude(effective_client, model, prompt)
    except anthropic.APIError as exc:
        raise ValidateSummarizeError(f"Claude Validate Summarize request failed: {exc}") from exc

    record_claude_usage(model, response.usage.input_tokens, response.usage.output_tokens)

    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None or tool_use.name != VALIDATE_SUMMARIZE_TOOL_NAME:
        raise ValidateSummarizeError(
            f"Claude did not return the expected tool call: {response.content!r}"
        )

    tool_input = _recover_leaked_recurrence_signal(tool_use.input)
    try:
        summary = str(tool_input["summary"])
        representative_ask = str(tool_input["representative_ask"])
        recurrence_signal = str(tool_input["recurrence_signal"])
    except (KeyError, TypeError) as exc:
        raise ValidateSummarizeError(
            f"Malformed Validate Summarize tool input: {tool_input!r}"
        ) from exc

    if recurrence_signal not in _RECURRENCE_SIGNAL_VALUES:
        raise ValidateSummarizeError(
            f"recurrence_signal must be one of {_RECURRENCE_SIGNAL_VALUES}, "
            f"got {recurrence_signal!r}"
        )

    return ValidationSummarizeResult(
        summary=summary, representative_ask=representative_ask, recurrence_signal=recurrence_signal
    )
