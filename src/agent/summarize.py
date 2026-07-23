"""Claude Summarize client (tasks.md T040, contracts/pipeline-stages.md § Summarize).

The only LLM-powered stage upstream of Rank — everything before it
(Fetch/Filter/Detect/Cluster) stays fully deterministic (Constitution
Principle I/II). Output is constrained to a structured tool call
({summary, rationale, confidence_score}) rather than free text, and
`confidence_score` is grounded in the deterministic signals passed in as
context (spike_ratio, cluster_post_count, filter-survival rate,
account-diversity) rather than invented from raw post text alone
(research.md §12).

Model name is read from `src/config.py` (T021), never hardcoded here, so it
can move from `claude-sonnet-5` to `claude-haiku-4-5-20251001` after T059's
week-3 reassessment without touching this module (research.md §3,
/speckit-analyze finding E1). Token spend is reported to the cost tracker
from T022.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import anthropic

from src.utils.cost_tracker import record_claude_usage
from src.utils.retry import retry_with_backoff

SUMMARIZE_TOOL_NAME = "submit_theme_summary"

_MAX_EXAMPLE_POSTS_IN_PROMPT = 20

_TOOL_SCHEMA = {
    "name": SUMMARIZE_TOOL_NAME,
    # Grammar-constrained generation — guarantees every required field is
    # present with the declared type. Added after two production failures
    # where confidence_score went missing entirely: a stray legacy-format
    # `</rationale>\n<parameter name="confidence_score">N` artifact leaked
    # into the rationale string instead of confidence_score landing in its
    # own field. See `_recover_leaked_confidence_score` below for a fallback
    # in case this pattern recurs anyway.
    "strict": True,
    "description": (
        "Submit a plain-language summary, rationale, and confidence score for "
        "why this cluster of posts does or doesn't represent a genuinely "
        "trending theme."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "summary": {
                "type": "string",
                "description": "Plain-language, one-to-two-sentence summary of the theme.",
            },
            "rationale": {
                "type": "string",
                "description": (
                    "Why this is (or isn't) trending right now, grounded in the "
                    "deterministic signals provided — not just the post text."
                ),
            },
            "confidence_score": {
                "type": "integer",
                "description": (
                    "0-100 STRENGTH OF EVIDENCE that this is a genuine, noteworthy "
                    "trend — not your confidence in your own analysis being "
                    "correct. A low score is the CORRECT answer when signals are "
                    "weak, not a hedge. Calibrate against the provided signals: "
                    "cluster_post_count=1 with no spike_ratio and 1 distinct "
                    "author -> 0-5. A handful of posts with weak/no spike signal "
                    "or low author diversity -> 5-25. A moderate spike_ratio "
                    "(roughly 3-5x baseline) with several distinct authors -> "
                    "30-65. A strong spike_ratio (>5x), high cluster_post_count, "
                    "and high account diversity -> 65-100. If your rationale "
                    "concludes this is NOT a genuine trend, confidence_score "
                    "MUST be 0-5 — do not output 6-15 as a polite minimum."
                ),
            },
        },
        "required": ["summary", "rationale", "confidence_score"],
        "additionalProperties": False,
    },
}

_RETRYABLE_ERRORS = (
    anthropic.APIConnectionError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


@dataclass(frozen=True)
class SummarizeInput:
    """One cluster's post texts + deterministic context signals
    (contracts/pipeline-stages.md § Summarize)."""

    topic_name: str
    post_texts: list[str]
    spike_ratio: float | None
    cluster_post_count: int
    filter_survival_rate: float
    account_diversity_count: int


@dataclass(frozen=True)
class SummarizeResult:
    summary: str
    rationale: str
    confidence_score: int


class SummarizeError(RuntimeError):
    """Raised on persistent Claude failure or a malformed tool response.

    Callers (the orchestrator) should catch this and exclude the affected
    Theme candidate with a logged note rather than failing the whole run
    (contracts/external-integrations.md § LLM).
    """


# Observed in production, two variants: (1) confidence_score missing from
# tool_input entirely, with its intended value trapped as trailing text in
# another string field via a stray legacy-format tool-call artifact, e.g.
# `...not a trend.</rationale>\n<parameter name="confidence_score">5`; and
# (2) confidence_score present and correct in its own field, but the *same*
# trailing artifact still gets appended onto another string field (e.g.
# rationale) regardless, leaving it corrupted even though nothing was lost.
# `strict: True` on the tool schema (above) should prevent this at the
# source; this is a defensive fallback in case it recurs anyway (e.g. after
# a future model switch per T059) — always strips the artifact from every
# string field, and only recovers confidence_score from it when that field
# wasn't already supplied on its own.
_LEAKED_PARAMETER_PATTERN = re.compile(r'</\w+>\s*<parameter name="confidence_score">\s*(\d+)\s*$')


def _recover_leaked_confidence_score(tool_input: dict) -> dict:
    has_confidence_score = "confidence_score" in tool_input
    cleaned = dict(tool_input)
    for key, value in tool_input.items():
        if not isinstance(value, str):
            continue
        match = _LEAKED_PARAMETER_PATTERN.search(value)
        if match is None:
            continue
        cleaned[key] = value[: match.start()].rstrip()
        if not has_confidence_score:
            cleaned["confidence_score"] = match.group(1)
            has_confidence_score = True
    return cleaned


def _build_prompt(data: SummarizeInput) -> str:
    examples = "\n".join(f"- {text}" for text in data.post_texts[:_MAX_EXAMPLE_POSTS_IN_PROMPT])
    spike_ratio_text = (
        f"{data.spike_ratio:.2f}x baseline"
        if data.spike_ratio is not None
        else "n/a (topic still within its 7-day observation period)"
    )
    return (
        f"Topic being monitored: {data.topic_name}\n\n"
        "Deterministic signals already computed upstream — ground your "
        "confidence_score in these, not in the post text alone:\n"
        f"- spike_ratio (current filtered activity ÷ historical baseline): {spike_ratio_text}\n"
        f"- cluster_post_count (posts in this cluster): {data.cluster_post_count}\n"
        f"- filter_survival_rate (share of fetched posts that passed the bot/noise "
        f"filter): {data.filter_survival_rate:.0%}\n"
        f"- distinct author count in this cluster: {data.account_diversity_count}\n\n"
        f"Posts in this cluster:\n{examples}\n\n"
        f"Call {SUMMARIZE_TOOL_NAME} with a plain-language summary, a rationale, "
        "and a confidence_score.\n\n"
        "IMPORTANT — confidence_score measures strength of trend evidence, not "
        "confidence in your reasoning. A single post from a single author with "
        "no spike_ratio is 0-5, not a moderate score. If your rationale says "
        "this is isolated / promotional / not a genuine trend, the score MUST "
        "be 0-5 — a low rationale conclusion paired with a moderate score is "
        "exactly the miscalibration this instruction exists to prevent.\n\n"
        "Write plain prose only in every field — no XML tags, no markup, no "
        "`<parameter>`-style text anywhere in summary or rationale."
    )


@retry_with_backoff(max_attempts=3, base_delay_seconds=0.2, exceptions=_RETRYABLE_ERRORS)
def _call_claude(client: anthropic.Anthropic, model: str, prompt: str) -> anthropic.types.Message:
    return client.messages.create(
        model=model,
        max_tokens=1024,
        tools=[_TOOL_SCHEMA],
        tool_choice={"type": "tool", "name": SUMMARIZE_TOOL_NAME},
        messages=[{"role": "user", "content": prompt}],
    )


def summarize_theme(
    data: SummarizeInput,
    *,
    api_key: str,
    model: str,
    client: anthropic.Anthropic | None = None,
) -> SummarizeResult:
    """Summarize one Theme candidate via Claude structured tool-call output.

    Raises `SummarizeError` after retry is exhausted, or if Claude's response
    doesn't carry the expected tool call / a valid 0-100 confidence score.
    """
    effective_client = client if client is not None else anthropic.Anthropic(api_key=api_key)
    prompt = _build_prompt(data)

    try:
        response = _call_claude(effective_client, model, prompt)
    except anthropic.APIError as exc:
        raise SummarizeError(f"Claude Summarize request failed: {exc}") from exc

    record_claude_usage(model, response.usage.input_tokens, response.usage.output_tokens)

    tool_use = next((block for block in response.content if block.type == "tool_use"), None)
    if tool_use is None or tool_use.name != SUMMARIZE_TOOL_NAME:
        raise SummarizeError(f"Claude did not return the expected tool call: {response.content!r}")

    tool_input = _recover_leaked_confidence_score(tool_use.input)
    try:
        summary = str(tool_input["summary"])
        rationale = str(tool_input["rationale"])
        confidence_score = int(tool_input["confidence_score"])
    except (KeyError, TypeError, ValueError) as exc:
        raise SummarizeError(f"Malformed Summarize tool input: {tool_input!r}") from exc

    if not 0 <= confidence_score <= 100:
        raise SummarizeError(
            f"confidence_score out of the required 0-100 range: {confidence_score}"
        )

    return SummarizeResult(summary=summary, rationale=rationale, confidence_score=confidence_score)
