"""`digest run`/`digest show` CLI commands (tasks.md T045/T049/T052;
contracts/cli-commands.md).

`run` triggers an on-demand pipeline run for all of a user's active topics,
or — via `--topic <name>` (User Story 2, T049) — a single named one, invoking
the exact same orchestrator entry point (`src.pipeline.orchestrator.
run_digest`) the scheduler (`src/scheduler/jobs.py`) uses for scheduled runs,
guaranteeing on-demand output format/quality matches a scheduled run (User
Story 2, Acceptance Scenario 2).

`show` renders a stored digest, grouped by topic. Without `--full`, each
Theme shows its 3-5 curated example posts (default), and Themes below
`CONFIDENCE_DISPLAY_THRESHOLD` are hidden entirely — a display-only filter
(the underlying Theme rows, DraftPost generation, etc. are never touched),
with a trailing "N additional low-confidence themes not shown" line per
topic when any are hidden. With `--full` (User Story 3, T052), every
underlying `SourcePost` for a topic is shown — both the ones clustered into
a Theme and the ones Filter excluded — each annotated with its
`filter_outcome`, satisfying FR-016's "every filtered and clustered post,
not just the shown examples," and every Theme is shown regardless of
confidence. `--topic <name>` scopes rendering to a single topic, still
rendering its outcome explicitly (FR-017) even when that topic has no Themes
this run.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select

from src.cli._common import NoCurrentUserError, resolve_current_user
from src.config import load_config
from src.db.scoped import scoped_select
from src.db.session import get_session
from src.logging_config import configure_logging
from src.models.digest import Digest, DigestRunType
from src.models.digest_topic_result import DigestTopicOutcome, DigestTopicResult
from src.models.source_post import SourcePost
from src.models.theme import Theme
from src.models.topic import Topic, TopicStatus
from src.pipeline.orchestrator import run_digest

# Below this confidence_score (0-100, see src/agent/summarize.py's tool-schema
# calibration bands), the default `digest show` view treats a Theme as noise
# and hides it. The Summarize prompt itself reserves 0-5 for "concludes this
# is NOT a genuine trend" and only starts describing a real "moderate spike"
# at 30+; production eval data showed the low-value entries cluttering
# digests clustering under confidence 10. 20 clears that noise floor with a
# 2x margin while staying safely under the 30 "moderate spike" floor, so
# nothing the model calibrated as a real trend is hidden by default. Tune
# here if eval data shifts; `--full` always bypasses this filter (FR-016).
CONFIDENCE_DISPLAY_THRESHOLD = 20


def _active_topics(session, user_id) -> list[Topic]:
    return (
        session.execute(scoped_select(Topic, user_id).where(Topic.status == TopicStatus.ACTIVE))
        .scalars()
        .all()
    )


def _active_topic_by_name(session, user_id, name: str) -> Topic | None:
    return session.execute(
        scoped_select(Topic, user_id).where(Topic.name == name, Topic.status == TopicStatus.ACTIVE)
    ).scalar_one_or_none()


def _digest_for_user(session, user_id, digest_id: uuid.UUID) -> Digest | None:
    return session.execute(
        scoped_select(Digest, user_id).where(Digest.id == digest_id)
    ).scalar_one_or_none()


def _print_digest(
    session, digest: Digest, *, topic_name: str | None = None, full: bool = False
) -> int:
    """Print `digest`, scoped to `topic_name` if given, returning a process
    exit code (0 on success, 1 if `topic_name` doesn't match anything in this
    digest)."""
    print(f"Digest {digest.id}")
    print(f"  status:       {digest.status.value}")
    print(f"  run_type:     {digest.run_type.value}")
    print(f"  started_at:   {digest.started_at.isoformat()}")
    completed_at = digest.completed_at.isoformat() if digest.completed_at else "-"
    print(f"  completed_at: {completed_at}")
    print()

    dtr_query = (
        select(DigestTopicResult, Topic)
        .join(Topic, DigestTopicResult.topic_id == Topic.id)
        .where(DigestTopicResult.digest_id == digest.id)
    )
    if topic_name is not None:
        dtr_query = dtr_query.where(Topic.name == topic_name)
    dtr_rows = session.execute(dtr_query.order_by(Topic.name)).all()

    if not dtr_rows:
        if topic_name is not None:
            print(f"No topic named {topic_name!r} in this digest.", file=sys.stderr)
            return 1
        print("No topics in this digest.")
        return 0

    for dtr, topic in dtr_rows:
        detail = f" ({dtr.error_detail})" if dtr.error_detail else ""
        print(f"== {topic.name} ==  outcome={dtr.outcome.value}{detail}")

        if dtr.outcome != DigestTopicOutcome.THEMES_PRESENT:
            # FR-017: state the explicit no-activity/all-noise/error outcome
            # rather than an empty or missing entry.
            if full:
                _print_source_posts(session, dtr_id=dtr.id, theme_id=None, indent="    ")
            print()
            continue

        themes = (
            session.execute(
                select(Theme).where(Theme.digest_topic_result_id == dtr.id).order_by(Theme.rank)
            )
            .scalars()
            .all()
        )
        if full:
            displayed_themes = themes
        else:
            # Display-layer filter only (per CONFIDENCE_DISPLAY_THRESHOLD's
            # docstring) — the underlying Theme rows are untouched, `--full`
            # still shows every one of them regardless of confidence.
            displayed_themes = [
                theme for theme in themes if theme.confidence_score >= CONFIDENCE_DISPLAY_THRESHOLD
            ]
        for theme in displayed_themes:
            print(
                f"  [rank {theme.rank}] confidence={theme.confidence_score}  "
                f"is_spike={theme.is_spike}  spike_ratio={theme.spike_ratio}"
            )
            print(f"      summary:   {theme.summary}")
            print(f"      rationale: {theme.rationale}")

            if full:
                # FR-016: every post clustered into this Theme, not just the
                # curated examples, each with its filter_outcome trail.
                _print_source_posts(
                    session,
                    dtr_id=None,
                    theme_id=theme.id,
                    indent="      ",
                    count_label=f"of {theme.cluster_post_count}",
                )
            else:
                examples = (
                    session.execute(
                        select(SourcePost).where(
                            SourcePost.theme_id == theme.id, SourcePost.is_example
                        )
                    )
                    .scalars()
                    .all()
                )
                print(f"      examples ({len(examples)} of {theme.cluster_post_count}):")
                for post in examples:
                    print(f"        - @{post.author_handle}: {post.text}")
            print()

        if not full:
            hidden_count = len(themes) - len(displayed_themes)
            if hidden_count > 0:
                noun = "theme" if hidden_count == 1 else "themes"
                print(
                    f"  {hidden_count} additional low-confidence {noun} not shown — "
                    "use --full to see everything."
                )

        if full:
            # FR-016: posts Filter excluded, or that Cluster left out of every
            # Theme, are still part of "the full source data" for this topic.
            excluded_count = _print_source_posts(
                session,
                dtr_id=dtr.id,
                theme_id=None,
                indent="  ",
                exclude_clustered=True,
                heading="excluded/unclustered posts",
            )
            if excluded_count == 0:
                print("  excluded/unclustered posts: none")
        print()

    return 0


def _print_source_posts(
    session,
    *,
    dtr_id,
    theme_id,
    indent: str,
    count_label: str | None = None,
    exclude_clustered: bool = False,
    heading: str = "source posts",
) -> int:
    """Print every `SourcePost` matching the given scope with its
    `filter_outcome` trail (FR-016), returning how many were printed.

    Exactly one of `dtr_id`/`theme_id` selects the scope: `theme_id` for a
    single Theme's clustered posts, `dtr_id` for every post tied to a topic's
    run (optionally excluding ones already clustered into a Theme, via
    `exclude_clustered`, to avoid double-printing them alongside their Theme).
    """
    query = select(SourcePost)
    if theme_id is not None:
        query = query.where(SourcePost.theme_id == theme_id)
    else:
        query = query.where(SourcePost.digest_topic_result_id == dtr_id)
        if exclude_clustered:
            query = query.where(SourcePost.theme_id.is_(None))

    posts = session.execute(query).scalars().all()
    if not posts:
        return 0

    label = f" ({len(posts)}{f' {count_label}' if count_label else ''})"
    print(f"{indent}{heading}{label}:")
    for post in posts:
        print(f"{indent}  - [{post.filter_outcome.value}] @{post.author_handle}: {post.text}")
    return len(posts)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="digest")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--topic", dest="topic_name", default=None)
    show_parser = subparsers.add_parser("show")
    show_parser.add_argument("digest_id")
    show_parser.add_argument("--topic", dest="topic_name", default=None)
    show_parser.add_argument("--full", action="store_true")

    args = parser.parse_args(argv)

    with get_session() as session:
        try:
            user = resolve_current_user(session)
        except NoCurrentUserError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        if args.command == "run":
            config = load_config()
            if args.topic_name is not None:
                topic = _active_topic_by_name(session, user.id, args.topic_name)
                if topic is None:
                    print(
                        f"No active topic named {args.topic_name!r} for this user.",
                        file=sys.stderr,
                    )
                    return 1
                topics = [topic]
            else:
                topics = _active_topics(session, user.id)

            if not topics:
                print("No active topics tracked — nothing to run.")
                return 0

            digest = run_digest(
                session, user, topics, run_type=DigestRunType.ON_DEMAND, config=config
            )
            print(f"Digest {digest.id} completed with status '{digest.status.value}'")
            return 0

        if args.command == "show":
            try:
                digest_id = uuid.UUID(args.digest_id)
            except ValueError:
                print(f"Invalid digest id: {args.digest_id!r}", file=sys.stderr)
                return 1

            digest = _digest_for_user(session, user.id, digest_id)
            if digest is None:
                print(f"No digest found with id {digest_id} for this user.", file=sys.stderr)
                return 1

            return _print_digest(session, digest, topic_name=args.topic_name, full=args.full)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
