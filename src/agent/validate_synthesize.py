"""Claude Validate Synthesize client — the top-level executive-summary/verdict
step over every theme Validate Summarize produced for one Idea Validation run
(spec.md §5.3, §7 of specs/002-idea-validation-mode: "the output reads as a
useful strategic input... not just a raw post dump").

A second, separate LLM-powered stage from `src/agent/validate_summarize.py`
(sibling module, same rationale that split `summarize.py`/`draft_post.py` in
the digest pipeline into two files rather than one — each prompt stays
independently readable/testable). Mirrors the same structured-tool-call
pattern (grammar-constrained schema, `retry_with_backoff`,
`record_claude_usage` cost tracking) but takes the *already-generated* theme
summaries plus the run's overall signal-strength numbers as input, not raw
post text — Validate Summarize has already distilled each cluster once, so
re-feeding raw posts here would just spend tokens without adding grounding.

No leaked-parameter-recovery logic here (unlike summarize.py/
validate_summarize.py): that defensive pattern exists specifically to
recover a value that leaked out of one field and into another when the
intended field went missing. This tool's schema has exactly one required
field (`verdict`), so there is no second field for a leaked value to hide
in — the tool call is either well-formed or it raises
`ValidateSynthesizeError`, a deliberate, simpler omission rather than a gap.
"""

from __future__ import annotations

from dataclasses import dataclass

import anthropic

from src.agent.validate_summarize import ValidationTheme
from src.utils.cost_tracker import record_claude_usage
from src.utils.retry import retry_with_backoff

VALIDATE_SYNTHESIZE_TOOL_NAME = "submit_validation_verdict"

_TOOL_SCHEMA = {
    "name": VALIDATE_SYNTHESIZE_TOOL_NAME,
    "strict": True,
    "description": (
        "Submit a short executive-summary verdict synthesizing every theme found for this "
        "Idea Validation run into one strategic read a client-facing strategist can act on."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "description": (
                    "A 3-5 sentence executive-summary paragraph for a strategist deciding "
                    "whether to pursue this idea further. Plain prose, no headers, no bullet "
                    "points, no XML tags. Must address, in order: "
                    "(1) is this a real, validated problem — grounded strictly in the themes "
                    "provided below, never invented or assumed beyond what's actually there; "
                    "(2) is the signal concentrated (a few themes with high "
                    "cluster_post_count/distinct_author_count) or fragmented (mostly isolated "
                    "singleton themes) — say which, using the actual counts given; "
                    "(3) do any of the provided themes describe an existing competitor or "
                    "product already targeting this problem — mention this ONLY if a theme "
                    "actually describes one; if none do, do not speculate that competitors "
                    "exist; (4) an honest recommendation — worth pursuing further, or too "
                    "crowded/thin. When the evidence is weak or fragmented, the honest "
                    "recommendation is caution or 'not yet validated', not a default-optimistic "
                    "'worth pursuing' — do not oversell thin evidence."
                ),
            },
        },
        "required": ["verdict"],
        "additionalProperties": False,
    },
}

_RETRYABLE_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)

# Same rationale/values as summarize.py's/validate_summarize.py's
# _CLAUDE_REQUEST_TIMEOUT — a hung call must fail fast into
# retry_with_backoff rather than block silently.
_CLAUDE_REQUEST_TIMEOUT = anthropic.Timeout(60.0, connect=10.0)


@dataclass(frozen=True)
class ValidateSynthesizeInput:
    """Every theme Validate Summarize produced for this run, plus the run's
    overall Signal Strength — the only context the verdict is grounded in."""

    problem_phrases: list[str]
    themes: list[ValidationTheme]
    total_relevant_count: int
    distinct_author_count: int
    posts_last_24h: int
    posts_last_7d: int


@dataclass(frozen=True)
class ValidationVerdictResult:
    verdict: str


class ValidateSynthesizeError(RuntimeError):
    """Raised on persistent Claude failure or a malformed tool response.

    Callers (`src/cli/idea_validate.py`) should catch this and omit the
    Verdict section from the readout with a logged note rather than failing
    the whole run — the same per-call failure-isolation principle
    `ValidateSummarizeError` follows for individual themes, applied here to
    the one run-level synthesis call.
    """


def _build_prompt(data: ValidateSynthesizeInput) -> str:
    phrases = ", ".join(f'"{phrase}"' for phrase in data.problem_phrases)
    theme_lines = []
    for i, theme in enumerate(data.themes, start=1):
        theme_lines.append(
            f"{i}. recurrence_signal={theme.recurrence_signal}  "
            f"cluster_post_count={theme.cluster_post_count}  "
            f"distinct_author_count={theme.distinct_author_count}\n"
            f"   summary: {theme.summary}\n"
            f"   representative_ask: {theme.representative_ask}"
        )
    themes_block = "\n".join(theme_lines)
    return (
        f"Problem statement being validated: {phrases}\n\n"
        "Overall signal strength for this run, across all themes combined:\n"
        f"- total_relevant_count: {data.total_relevant_count}\n"
        f"- distinct_author_count: {data.distinct_author_count}\n"
        f"- posts_last_24h: {data.posts_last_24h}\n"
        f"- posts_last_7d: {data.posts_last_7d}\n\n"
        f"Every theme found ({len(data.themes)} total), already summarized — this is the "
        f"complete set of evidence available, do not assume anything beyond it:\n{themes_block}\n\n"
        f"Call {VALIDATE_SYNTHESIZE_TOOL_NAME} with a verdict synthesizing the above into one "
        "strategic read.\n\n"
        "IMPORTANT — ground every claim in the themes and counts given above. Do not invent "
        "posts, evidence, or competitors that aren't actually described in a theme. If most "
        "themes are 'isolated' singletons, say the signal is fragmented, not concentrated. If "
        "the evidence is thin, the honest recommendation reflects that — don't hedge toward a "
        "positive read as a default.\n\n"
        "Write plain prose only — no XML tags, no markup, no `<parameter>`-style text."
    )


@retry_with_backoff(max_attempts=3, base_delay_seconds=0.2, exceptions=_RETRYABLE_ERRORS)
def _call_claude(client: anthropic.Anthropic, model: str, prompt: str) -> anthropic.types.Message:
    return client.messages.create(
        model=model,
        max_tokens=1024,
        tools=[_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": VALIDATE_SYNTHESIZE_TOOL_NAME},
        messages=[{"role": "user", "content": prompt}],
    )


def synthesize_validation_verdict(
    data: ValidateSynthesizeInput,
    *,
    api_key: str,
    model: str,
    client: anthropic.Anthropic | None = None,
) -> ValidationVerdictResult:
    """Synthesize every theme in `data.themes` plus the run's overall signal
    strength into one executive-summary verdict via Claude structured
    tool-call output.

    Raises `ValidateSynthesizeError` after retry is exhausted, or if
    Claude's response doesn't carry the expected tool call / a non-empty
    `verdict` string.
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
        raise ValidateSynthesizeError(f"Claude Validate Synthesize request failed: {exc}") from exc

    record_claude_usage(model, response.usage.input_tokens, response.usage.output_tokens)

    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None or tool_use.name != VALIDATE_SYNTHESIZE_TOOL_NAME:
        raise ValidateSynthesizeError(
            f"Claude did not return the expected tool call: {response.content!r}"
        )

    try:
        verdict = str(tool_use.input["verdict"])
    except (KeyError, TypeError) as exc:
        raise ValidateSynthesizeError(
            f"Malformed Validate Synthesize tool input: {tool_use.input!r}"
        ) from exc

    if not verdict.strip():
        raise ValidateSynthesizeError("Validate Synthesize returned an empty verdict.")

    return ValidationVerdictResult(verdict=verdict)
