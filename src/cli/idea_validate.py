"""`idea-validate run` CLI command (tasks.md T015, contracts/cli-commands.md
§ `idea-validate run`).

Unlike every other `cli/*.py` command, this one does not call
`resolve_current_user` and never opens a DB session — both the Fetch-provider
API key and `ANTHROPIC_API_KEY` are app-level credentials already
(`src/config.py`), and this mode persists nothing (research.md §1). Fetch
goes through the same `FETCH_PROVIDER` abstraction every other command uses
(`src.pipeline.fetch_provider.get_fetch_provider_for_query`, the
query-string-accepting sibling of the `get_fetch_provider()` the digest
pipeline calls) — this mode respects `FETCH_PROVIDER` and defaults to
TwitterAPIs.com like everything else, rather than hardcoding TwitterAPI.io.
Wires Query Construction -> Fetch -> Relevance Filter -> Bot/Noise Filter ->
Signal Strength -> Cluster -> Validate Summarize -> Validation Readout for
one synchronous run, then prints (and optionally writes) the result. No
`Digest`/`Theme`/`SourcePost`/`DraftPost`/`PostingMode` row is ever touched
(spec.md §3 non-goals, contracts/cli-commands.md's "MUST NOT write to any
application-owned table").
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from src.agent.validate_summarize import (
    ValidateSummarizeError,
    ValidateSummarizeInput,
    ValidationTheme,
    summarize_validation_theme,
)
from src.config import ConfigError, load_config
from src.logging_config import configure_logging, get_logger
from src.models.source_post import FilterOutcome
from src.pipeline.cluster import cluster_posts
from src.pipeline.fetch import DEFAULT_LOOKBACK
from src.pipeline.fetch_provider import get_fetch_provider_for_query
from src.pipeline.filter import filter_posts
from src.pipeline.idea_query_builder import IdeaValidationQuery, build_idea_validation_query
from src.pipeline.relevance_filter import RelevanceOutcome, filter_relevance
from src.pipeline.signal_strength import compute_signal_strength
from src.report.validation_readout import build_validation_readout, render_validation_readout

# Same 3-5 curated-example convention as orchestrator.py's
# _MIN_EXAMPLE_POSTS/_MAX_EXAMPLE_POSTS.
_MIN_EXAMPLE_POSTS = 3
_MAX_EXAMPLE_POSTS = 5

log = get_logger(__name__)


class IdeaValidateCommandError(RuntimeError):
    """Raised for a rejected `idea-validate run` invocation (e.g. no
    `--phrase` given, or an unparseable `--since`/`--until`)."""


def _parse_iso8601(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise IdeaValidateCommandError(f"Invalid ISO 8601 datetime: {value!r}.") from exc
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _select_example_post_texts(post_texts: list[str]) -> list[str]:
    """3-5 curated examples per theme (mirrors orchestrator.py's
    `_select_example_post_ids`) — or every post, if the cluster has fewer
    than the 3-post minimum to begin with."""
    limit = max(_MIN_EXAMPLE_POSTS, min(_MAX_EXAMPLE_POSTS, len(post_texts)))
    return post_texts[:limit]


def run_idea_validation(
    query: IdeaValidationQuery,
    *,
    anthropic_api_key: str,
    claude_model: str,
) -> str:
    """Run the full Idea Validation pipeline for `query` and return the
    rendered readout.

    Never raises out to the caller on a Fetch failure or a single theme's
    Validate Summarize failure — both are surfaced in the readout/log
    instead, never a stack trace or a silently empty readout
    (contracts/cli-commands.md § Errors).
    """
    fetch_query = build_idea_validation_query(
        query.phrases, query.exclude_terms, query.since, query.until
    )
    # Same FETCH_PROVIDER resolution the digest pipeline uses
    # (src/pipeline/orchestrator.py calls get_fetch_provider() the same
    # inline way) — resolved here, not injected, so credentials never pass
    # through this function's own signature.
    fetch_result = get_fetch_provider_for_query()(fetch_query)

    if not fetch_result.ok:
        log.error("fetch failed for idea validation query: %s", fetch_result.error.detail)
        now = datetime.now(UTC)
        empty_signal = compute_signal_strength([], now=now)
        readout = build_validation_readout(query, empty_signal, [], now=now)
        return (
            f"Fetch error ({fetch_result.error.kind.value}): {fetch_result.error.detail}\n\n"
            f"{render_validation_readout(readout)}"
        )

    raw_posts = fetch_result.posts or []

    relevant = filter_relevance(raw_posts, query.exclude_terms)
    relevance_kept_posts = [
        r.post for r in relevant if r.relevance_outcome == RelevanceOutcome.KEPT
    ]

    filtered = filter_posts(relevance_kept_posts)
    kept_posts = [f.post for f in filtered if f.filter_outcome == FilterOutcome.KEPT]

    now = datetime.now(UTC)
    signal_strength = compute_signal_strength(kept_posts, now=now)

    candidates = cluster_posts(kept_posts)

    themes: list[ValidationTheme] = []
    for candidate in candidates:
        distinct_author_count = len({post.author_handle for post in candidate.posts})
        post_texts = [post.text for post in candidate.posts]
        try:
            result = summarize_validation_theme(
                ValidateSummarizeInput(
                    problem_phrases=query.phrases,
                    post_texts=post_texts,
                    cluster_post_count=candidate.post_count,
                    distinct_author_count=distinct_author_count,
                ),
                api_key=anthropic_api_key,
                model=claude_model,
            )
        except ValidateSummarizeError as exc:
            log.error(
                "Validate Summarize failed for a theme, dropping it from the readout: %s", exc
            )
            continue

        themes.append(
            ValidationTheme(
                summary=result.summary,
                representative_ask=result.representative_ask,
                recurrence_signal=result.recurrence_signal,
                cluster_post_count=candidate.post_count,
                distinct_author_count=distinct_author_count,
                example_post_texts=_select_example_post_texts(post_texts),
            )
        )

    readout = build_validation_readout(query, signal_strength, themes, now=now)
    return render_validation_readout(readout)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="idea-validate")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument(
        "--phrase",
        dest="phrases",
        action="append",
        default=[],
        help="A problem-describing phrase to search for. Repeatable; at least one required.",
    )
    run_parser.add_argument(
        "--exclude-term",
        dest="exclude_terms",
        action="append",
        default=[],
        help="A term/phrase to exclude, both from the query and post-fetch. Repeatable.",
    )
    run_parser.add_argument("--since", default=None, help="ISO 8601 datetime, window start.")
    run_parser.add_argument("--until", default=None, help="ISO 8601 datetime, window end.")
    run_parser.add_argument(
        "--out", default=None, help="Also write the rendered readout to this path."
    )

    args = parser.parse_args(argv)

    try:
        if not args.phrases:
            raise IdeaValidateCommandError(
                "At least one --phrase is required (e.g. --phrase \"can't find sublet\")."
            )

        until = _parse_iso8601(args.until) if args.until else datetime.now(UTC)
        since = _parse_iso8601(args.since) if args.since else (until - DEFAULT_LOOKBACK)
        query = IdeaValidationQuery(
            phrases=args.phrases, exclude_terms=args.exclude_terms, since=since, until=until
        )

        config = load_config()
        rendered = run_idea_validation(
            query,
            anthropic_api_key=config.anthropic_api_key,
            claude_model=config.claude_model,
        )
    except (IdeaValidateCommandError, ValueError, ConfigError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(rendered)
    if args.out:
        with open(args.out, "w") as f:
            f.write(rendered)
            f.write("\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
