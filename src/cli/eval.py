"""`eval label <stage>` and `eval report [--stage X]` CLI commands.

One shared `EvaluationLabel` table covers every judgment-making stage of the
pipeline — Filter, Detect, Cluster, Summarize, Draft Post, Digest — rather
than a separate table per stage (src/models/evaluation_label.py).

`label` samples real, unlabeled items straight out of the pipeline's own
tables (SourcePost/Theme/DraftPost/Digest) — never synthetic data — shows
the same context a human reviewer needs to judge that stage's decision, and
records a label. Pass `--id <uuid>` to label one specific item instead of
random sampling (still scoped to the current user, and still rejected if
already labeled by them). `report` aggregates every label recorded so far
into an accuracy % (binary stages) or average rating (rated stages),
including the SC-011 KPI (Digest "worth reading" rating).

Detect, Cluster, and Summarize all sample from `Theme` — there's no separate
"detect result" entity in this schema; the spike call and cluster membership
both live on `Theme` already, so each stage just judges a different aspect
of the same row.

Mirrors src/cli/drafts.py's structure: resolve_current_user, scoped_select,
get_session as a context manager, EOF-safe interactive prompts.
"""

from __future__ import annotations

import argparse
import random
import sys
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.cli._common import NoCurrentUserError, resolve_current_user
from src.db.scoped import scoped_select
from src.db.session import get_session
from src.logging_config import configure_logging
from src.models.digest import Digest
from src.models.digest_topic_result import DigestTopicResult
from src.models.draft_post import DraftPost
from src.models.evaluation_label import (
    BINARY_STAGES,
    CORRECT,
    INCORRECT,
    EvalStage,
    EvaluationLabel,
    valid_label_values,
)
from src.models.source_post import SourcePost
from src.models.theme import Theme
from src.models.topic import Topic

DEFAULT_SAMPLE_COUNT = 5
_MAX_CONTEXT_POSTS = 5


class EvalCommandError(RuntimeError):
    """Raised for a rejected eval command (e.g. a bad --count)."""


class _Quit(Exception):
    """Internal signal: the user asked to end the labeling session early."""


class _Skip(Exception):
    """Internal signal: the user asked to skip the current item."""


def _render_filter(session: Session, post: SourcePost) -> str:
    return "\n".join(
        [
            f"target_id: {post.id}",
            f"author: @{post.author_handle}",
            f"posted_at: {post.posted_at.isoformat()}",
            f"text: {post.text}",
            f"Filter's decision: {post.filter_outcome.value}",
        ]
    )


def _theme_topic_name(session: Session, theme: Theme) -> str:
    dtr = session.get(DigestTopicResult, theme.digest_topic_result_id)
    topic = session.get(Topic, dtr.topic_id) if dtr is not None else None
    return topic.name if topic is not None else "?"


def _theme_member_posts(session: Session, theme: Theme) -> list[SourcePost]:
    return (
        session.execute(
            select(SourcePost)
            .where(SourcePost.theme_id == theme.id)
            .order_by(SourcePost.is_example.desc())
            .limit(_MAX_CONTEXT_POSTS)
        )
        .scalars()
        .all()
    )


def _render_detect(session: Session, theme: Theme) -> str:
    lines = [
        f"target_id: {theme.id}",
        f"topic: {_theme_topic_name(session, theme)}",
        f"is_spike: {theme.is_spike}",
        f"spike_ratio: {theme.spike_ratio}",
        f"cluster_post_count: {theme.cluster_post_count}",
        f"confidence_score: {theme.confidence_score}",
        "example posts (for grounding, in hindsight):",
    ]
    for post in _theme_member_posts(session, theme):
        lines.append(f"  @{post.author_handle}: {post.text}")
    return "\n".join(lines)


def _render_cluster(session: Session, theme: Theme) -> str:
    lines = [
        f"target_id: {theme.id}",
        f"topic: {_theme_topic_name(session, theme)}",
        f"cluster_post_count: {theme.cluster_post_count}",
        "member posts:",
    ]
    for post in _theme_member_posts(session, theme):
        lines.append(f"  @{post.author_handle}: {post.text}")
    return "\n".join(lines)


def _render_summarize(session: Session, theme: Theme) -> str:
    return "\n".join(
        [
            f"target_id: {theme.id}",
            f"topic: {_theme_topic_name(session, theme)}",
            f"summary: {theme.summary}",
            f"rationale: {theme.rationale}",
            f"confidence_score: {theme.confidence_score}",
            f"is_spike: {theme.is_spike}  spike_ratio: {theme.spike_ratio}",
        ]
    )


def _render_draft(session: Session, draft: DraftPost) -> str:
    lines = [
        f"target_id: {draft.id}",
        f"draft_text: {draft.draft_text}",
        f"confidence_score: {draft.confidence_score}",
        f"status: {draft.status.value}",
    ]
    theme = session.get(Theme, draft.theme_id)
    if theme is not None:
        lines.append(f"theme summary: {theme.summary}")
        lines.append(f"theme rationale: {theme.rationale}")
    return "\n".join(lines)


def _render_digest(session: Session, digest: Digest) -> str:
    lines = [
        f"target_id: {digest.id}",
        f"run_type: {digest.run_type.value}",
        f"status: {digest.status.value}",
        f"started_at: {digest.started_at.isoformat()}",
    ]
    results = (
        session.execute(select(DigestTopicResult).where(DigestTopicResult.digest_id == digest.id))
        .scalars()
        .all()
    )
    for dtr in results:
        topic = session.get(Topic, dtr.topic_id)
        topic_name = topic.name if topic is not None else "?"
        lines.append(f"  topic={topic_name} outcome={dtr.outcome.value}")
        themes = (
            session.execute(
                select(Theme).where(Theme.digest_topic_result_id == dtr.id).order_by(Theme.rank)
            )
            .scalars()
            .all()
        )
        for theme in themes:
            lines.append(f"    [rank {theme.rank}] {theme.summary}")
    return "\n".join(lines)


@dataclass(frozen=True)
class _StageSpec:
    model: type
    question: str
    render: Callable[[Session, object], str]


_STAGE_SPECS: dict[EvalStage, _StageSpec] = {
    EvalStage.FILTER: _StageSpec(
        model=SourcePost,
        question="Was this bot/not-bot decision correct?",
        render=_render_filter,
    ),
    EvalStage.DETECT: _StageSpec(
        model=Theme,
        question="Was this spike/no-spike call right, in hindsight?",
        render=_render_detect,
    ),
    EvalStage.CLUSTER: _StageSpec(
        model=Theme,
        question="Was this grouping sensible?",
        render=_render_cluster,
    ),
    EvalStage.SUMMARIZE: _StageSpec(
        model=Theme,
        question="Rate the summary/rationale quality.",
        render=_render_summarize,
    ),
    EvalStage.DRAFT: _StageSpec(
        model=DraftPost,
        question="Rate the draft quality.",
        render=_render_draft,
    ),
    EvalStage.DIGEST: _StageSpec(
        model=Digest,
        question="Rate the digest's overall usefulness (SC-011).",
        render=_render_digest,
    ),
}


def _sample_targets(
    session: Session, user_id: uuid.UUID, stage: EvalStage, count: int
) -> list[object]:
    """Return up to `count` real, unlabeled items for `stage`, scoped to
    `user_id` and excluding anything `user_id` has already labeled for this
    stage (a different user may still independently label the same item)."""
    spec = _STAGE_SPECS[stage]
    labeled_ids = set(
        session.execute(
            select(EvaluationLabel.target_id).where(
                EvaluationLabel.stage == stage,
                EvaluationLabel.labeled_by_user_id == user_id,
            )
        ).scalars()
    )
    stmt = scoped_select(spec.model, user_id)
    if labeled_ids:
        stmt = stmt.where(spec.model.id.notin_(labeled_ids))
    candidates = session.execute(stmt).scalars().all()
    if not candidates:
        return []
    return random.sample(candidates, min(count, len(candidates)))


def _lookup_target(
    session: Session, user_id: uuid.UUID, stage: EvalStage, target_id: uuid.UUID
) -> object:
    """Return the single `stage` item identified by `target_id`, scoped to
    `user_id` (FR-015 — same ownership scoping `_sample_targets` uses, so
    `--id` can't be used to reach into another user's data).

    Raises EvalCommandError if no such item exists (or isn't owned by this
    user) or if this user has already labeled it for this stage — `--id`
    is meant to target one specific item, not silently no-op or double-label.
    """
    spec = _STAGE_SPECS[stage]
    target = session.execute(
        scoped_select(spec.model, user_id).where(spec.model.id == target_id)
    ).scalar_one_or_none()
    if target is None:
        raise EvalCommandError(f"No '{stage.value}' item with id {target_id} found.")

    already_labeled = session.execute(
        select(EvaluationLabel.id).where(
            EvaluationLabel.stage == stage,
            EvaluationLabel.target_id == target_id,
            EvaluationLabel.labeled_by_user_id == user_id,
        )
    ).scalar_one_or_none()
    if already_labeled is not None:
        raise EvalCommandError(
            f"'{stage.value}' item {target_id} was already labeled by this user."
        )
    return target


def _prompt_label(stage: EvalStage) -> str:
    """Prompt until a valid label (or skip/quit) is entered. Raises `_Skip`
    or `_Quit`; `EOFError` propagates to the caller to end the session."""
    if stage in BINARY_STAGES:
        prompt = "Correct? [y/n, s=skip, q=quit]: "
    else:
        prompt = "Rating (1-5, s=skip, q=quit): "

    while True:
        answer = input(prompt).strip().lower()
        if answer in ("q", "quit"):
            raise _Quit()
        if answer in ("s", "skip"):
            raise _Skip()
        if stage in BINARY_STAGES:
            if answer in ("y", "yes", CORRECT):
                return CORRECT
            if answer in ("n", "no", INCORRECT):
                return INCORRECT
        elif answer in valid_label_values(stage):
            return answer
        print(f"Please enter one of {sorted(valid_label_values(stage))} (or s/q).", file=sys.stderr)


def _prompt_notes() -> str | None:
    notes = input("Notes (optional, Enter to skip): ").strip()
    return notes or None


def _run_label(
    session: Session,
    user_id: uuid.UUID,
    stage: EvalStage,
    count: int,
    target_id: uuid.UUID | None = None,
) -> int:
    if target_id is not None:
        targets = [_lookup_target(session, user_id, stage, target_id)]
    else:
        targets = _sample_targets(session, user_id, stage, count)
        if not targets:
            print(f"No unlabeled '{stage.value}' items available.", file=sys.stderr)
            return 0

    spec = _STAGE_SPECS[stage]
    labeled = 0
    for target in targets:
        print("---")
        print(spec.render(session, target))
        print(spec.question)
        try:
            label_type = _prompt_label(stage)
            notes = _prompt_notes()
        except _Skip:
            continue
        except _Quit:
            break
        except EOFError:
            print("\nAborted: labeling session ended (EOF).", file=sys.stderr)
            break

        session.add(
            EvaluationLabel(
                stage=stage,
                target_id=target.id,
                label_type=label_type,
                notes=notes,
                labeled_by_user_id=user_id,
            )
        )
        session.commit()
        labeled += 1
        print(f"Labeled {label_type}.")

    print(f"Labeled {labeled}/{len(targets)} item(s) for stage '{stage.value}'.")
    return 0


def _compute_report(
    session: Session, user_id: uuid.UUID, stage: EvalStage | None
) -> dict[EvalStage, dict | None]:
    stmt = scoped_select(EvaluationLabel, user_id)
    if stage is not None:
        stmt = stmt.where(EvaluationLabel.stage == stage)
    labels = session.execute(stmt).scalars().all()

    values_by_stage: dict[EvalStage, list[str]] = defaultdict(list)
    for label in labels:
        values_by_stage[label.stage].append(label.label_type)

    stages_to_show = [stage] if stage is not None else list(EvalStage)
    report: dict[EvalStage, dict | None] = {}
    for s in stages_to_show:
        values = values_by_stage.get(s, [])
        if not values:
            report[s] = None
        elif s in BINARY_STAGES:
            correct = sum(1 for v in values if v == CORRECT)
            report[s] = {"kind": "binary", "correct": correct, "total": len(values)}
        else:
            ratings = [int(v) for v in values]
            report[s] = {"kind": "rating", "avg": sum(ratings) / len(ratings), "n": len(ratings)}
    return report


def _print_report(report: dict[EvalStage, dict | None]) -> None:
    for stage, stats in report.items():
        label = stage.value.ljust(10)
        if stats is None:
            print(f"{label} no labels yet")
        elif stats["kind"] == "binary":
            pct = 100 * stats["correct"] / stats["total"]
            print(f"{label} accuracy={pct:.1f}% ({stats['correct']}/{stats['total']})")
        else:
            suffix = "  <- SC-011 KPI" if stage == EvalStage.DIGEST else ""
            print(f"{label} avg_rating={stats['avg']:.2f} (n={stats['n']}){suffix}")


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(
        prog="eval",
        description=(
            "Human-in-the-loop evaluation for every judgment-making pipeline stage: "
            "Filter, Detect, Cluster, Summarize, Draft Post, Digest."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    label_parser = subparsers.add_parser(
        "label", help="Sample and label real, unlabeled items from one stage."
    )
    label_parser.add_argument("stage", choices=[s.value for s in EvalStage])
    label_parser.add_argument(
        "--count",
        "-n",
        type=int,
        default=DEFAULT_SAMPLE_COUNT,
        help=f"How many unlabeled items to sample (default {DEFAULT_SAMPLE_COUNT}). "
        "Ignored when --id is given.",
    )
    label_parser.add_argument(
        "--id",
        dest="target_id",
        default=None,
        help="Label this specific item by UUID instead of random sampling.",
    )

    report_parser = subparsers.add_parser(
        "report", help="Show accuracy/average-rating across labels recorded so far."
    )
    report_parser.add_argument(
        "--stage", dest="stage", default=None, choices=[s.value for s in EvalStage]
    )

    args = parser.parse_args(argv)

    with get_session() as session:
        try:
            user = resolve_current_user(session)
        except NoCurrentUserError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        try:
            if args.command == "label":
                if args.count < 1:
                    raise EvalCommandError("--count must be at least 1.")
                target_id = None
                if args.target_id is not None:
                    try:
                        target_id = uuid.UUID(args.target_id)
                    except ValueError as exc:
                        raise EvalCommandError(
                            f"--id must be a valid UUID, got {args.target_id!r}."
                        ) from exc
                return _run_label(session, user.id, EvalStage(args.stage), args.count, target_id)

            if args.command == "report":
                stage = EvalStage(args.stage) if args.stage else None
                _print_report(_compute_report(session, user.id, stage))
                return 0
        except EvalCommandError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
