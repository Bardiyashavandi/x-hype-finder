"""Unit tests for `eval label <stage>` and `eval report` (src/cli/eval.py).

Exercises the shared EvaluationLabel table across all six pipeline stages:
sampling only surfaces real, unlabeled items scoped to the current user;
binary/rating input is validated before being recorded; skip/quit/EOF each
behave distinctly (no partial row on EOF); and `report` aggregates
accuracy/average-rating per stage, scoped per-user like every other CLI
command here (FR-015).
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

import src.cli.eval as eval_cli
from src.models.digest import Digest, DigestRunType, DigestStatus
from src.models.digest_topic_result import DigestTopicOutcome, DigestTopicResult
from src.models.draft_post import DraftPost, DraftPostStatus
from src.models.evaluation_label import EvalStage, EvaluationLabel
from src.models.source_post import FilterOutcome, SourcePost
from src.models.theme import Theme
from src.models.topic import Topic
from src.models.user import User

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _run_cli(db_session, argv: list[str], monkeypatch, *, as_email: str) -> int:
    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(eval_cli, "get_session", fake_get_session)
    monkeypatch.setenv("XHF_USER_EMAIL", as_email)
    return eval_cli.main(argv)


def _scripted_input(monkeypatch, answers: list[str]) -> None:
    it = iter(answers)
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(it))


@pytest.fixture()
def user(db_session) -> User:
    u = User(email="pilot@example.com", x_account_handle="pilot")
    db_session.add(u)
    db_session.flush()
    return u


@pytest.fixture()
def other_user(db_session) -> User:
    u = User(email="other@example.com", x_account_handle="other")
    db_session.add(u)
    db_session.flush()
    return u


def _seed_chain(db_session, user: User, *, n_posts: int = 2) -> dict:
    """Build one full Topic -> Digest -> DigestTopicResult -> Theme ->
    SourcePost(s) -> DraftPost chain, owned by `user`."""
    topic = Topic(user_id=user.id, name="$TEST", x_handles=[])
    db_session.add(topic)
    db_session.flush()

    digest = Digest(
        user_id=user.id,
        run_type=DigestRunType.ON_DEMAND,
        started_at=NOW,
        completed_at=NOW,
        status=DigestStatus.COMPLETED,
    )
    db_session.add(digest)
    db_session.flush()

    dtr = DigestTopicResult(
        digest_id=digest.id, topic_id=topic.id, outcome=DigestTopicOutcome.THEMES_PRESENT
    )
    db_session.add(dtr)
    db_session.flush()

    theme = Theme(
        digest_topic_result_id=dtr.id,
        summary="Something is trending.",
        rationale="Because of X.",
        confidence_score=80,
        is_spike=True,
        spike_ratio=3.5,
        cluster_post_count=n_posts,
        rank=1,
    )
    db_session.add(theme)
    db_session.flush()

    posts = []
    for i in range(n_posts):
        post = SourcePost(
            topic_id=topic.id,
            digest_topic_result_id=dtr.id,
            x_post_id=f"post-{i}",
            author_handle=f"user_{i}",
            text=f"Post number {i}.",
            posted_at=NOW,
            filter_outcome=FilterOutcome.KEPT,
            theme_id=theme.id,
            is_example=(i == 0),
        )
        db_session.add(post)
        posts.append(post)
    db_session.flush()

    draft = DraftPost(
        theme_id=theme.id,
        user_id=user.id,
        draft_text="A draft post.",
        confidence_score=80,
        status=DraftPostStatus.HELD_MANUAL,
    )
    db_session.add(draft)
    db_session.flush()

    return {
        "topic": topic,
        "digest": digest,
        "dtr": dtr,
        "theme": theme,
        "posts": posts,
        "draft": draft,
    }


# --- label: binary stages ---------------------------------------------------


def test_label_filter_records_correct(db_session, user, monkeypatch, capsys):
    chain = _seed_chain(db_session, user, n_posts=1)
    _scripted_input(monkeypatch, ["y", ""])

    exit_code = _run_cli(
        db_session, ["label", "filter", "--count", "1"], monkeypatch, as_email=user.email
    )

    assert exit_code == 0
    labels = db_session.execute(select(EvaluationLabel)).scalars().all()
    assert len(labels) == 1
    assert labels[0].stage == EvalStage.FILTER
    assert labels[0].target_id == chain["posts"][0].id
    assert labels[0].label_type == "correct"
    assert labels[0].labeled_by_user_id == user.id

    out = capsys.readouterr().out
    assert "Filter's decision" in out
    assert "Labeled 1/1" in out


def test_label_binary_rejects_invalid_then_accepts(db_session, user, monkeypatch):
    chain = _seed_chain(db_session, user, n_posts=1)
    _scripted_input(monkeypatch, ["maybe", "n", ""])

    exit_code = _run_cli(
        db_session, ["label", "detect", "--count", "1"], monkeypatch, as_email=user.email
    )

    assert exit_code == 0
    labels = db_session.execute(select(EvaluationLabel)).scalars().all()
    assert len(labels) == 1
    assert labels[0].stage == EvalStage.DETECT
    assert labels[0].target_id == chain["theme"].id
    assert labels[0].label_type == "incorrect"


# --- label: rated stages -----------------------------------------------------


def test_label_rating_rejects_out_of_range_then_accepts(db_session, user, monkeypatch):
    _seed_chain(db_session, user, n_posts=1)
    _scripted_input(monkeypatch, ["6", "0", "abc", "4", ""])

    exit_code = _run_cli(
        db_session, ["label", "summarize", "--count", "1"], monkeypatch, as_email=user.email
    )

    assert exit_code == 0
    labels = db_session.execute(select(EvaluationLabel)).scalars().all()
    assert len(labels) == 1
    assert labels[0].stage == EvalStage.SUMMARIZE
    assert labels[0].label_type == "4"


# --- skip / quit / EOF -------------------------------------------------------


def test_skip_leaves_item_unlabeled_and_resamplable(db_session, user, monkeypatch):
    _seed_chain(db_session, user, n_posts=1)
    _scripted_input(monkeypatch, ["s"])

    exit_code = _run_cli(
        db_session, ["label", "filter", "--count", "1"], monkeypatch, as_email=user.email
    )

    assert exit_code == 0
    assert db_session.execute(select(EvaluationLabel)).scalars().all() == []


def test_quit_stops_before_labeling_remaining_items(db_session, user, monkeypatch, capsys):
    _seed_chain(db_session, user, n_posts=3)
    _scripted_input(monkeypatch, ["y", "", "q"])

    exit_code = _run_cli(
        db_session, ["label", "filter", "--count", "3"], monkeypatch, as_email=user.email
    )

    assert exit_code == 0
    labels = db_session.execute(select(EvaluationLabel)).scalars().all()
    assert len(labels) == 1
    assert "Labeled 1/3" in capsys.readouterr().out


def test_eof_aborts_without_partial_row(db_session, user, monkeypatch):
    _seed_chain(db_session, user, n_posts=1)

    def raise_eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    exit_code = _run_cli(
        db_session, ["label", "filter", "--count", "1"], monkeypatch, as_email=user.email
    )

    assert exit_code == 0
    assert db_session.execute(select(EvaluationLabel)).scalars().all() == []


# --- sampling behavior --------------------------------------------------------


def test_already_labeled_items_excluded_from_next_sample(db_session, user, monkeypatch, capsys):
    _seed_chain(db_session, user, n_posts=1)
    _scripted_input(monkeypatch, ["y", ""])
    _run_cli(db_session, ["label", "filter", "--count", "1"], monkeypatch, as_email=user.email)

    exit_code = _run_cli(
        db_session, ["label", "filter", "--count", "1"], monkeypatch, as_email=user.email
    )

    assert exit_code == 0
    assert "No unlabeled 'filter' items available." in capsys.readouterr().err
    assert len(db_session.execute(select(EvaluationLabel)).scalars().all()) == 1


def test_same_theme_can_be_labeled_for_different_stages(db_session, user, monkeypatch):
    chain = _seed_chain(db_session, user, n_posts=1)
    _scripted_input(monkeypatch, ["y", ""])
    _run_cli(db_session, ["label", "detect", "--count", "1"], monkeypatch, as_email=user.email)

    _scripted_input(monkeypatch, ["n", ""])
    _run_cli(db_session, ["label", "cluster", "--count", "1"], monkeypatch, as_email=user.email)

    labels = db_session.execute(select(EvaluationLabel)).scalars().all()
    assert {label.stage for label in labels} == {EvalStage.DETECT, EvalStage.CLUSTER}
    assert all(label.target_id == chain["theme"].id for label in labels)


def test_count_below_one_is_rejected(db_session, user, monkeypatch, capsys):
    _seed_chain(db_session, user, n_posts=1)

    exit_code = _run_cli(
        db_session, ["label", "filter", "--count", "0"], monkeypatch, as_email=user.email
    )

    assert exit_code == 1
    assert "--count must be at least 1" in capsys.readouterr().err


# --- render smoke tests for the remaining stages ------------------------------


def test_label_digest_smoke(db_session, user, monkeypatch, capsys):
    _seed_chain(db_session, user, n_posts=1)
    _scripted_input(monkeypatch, ["5", ""])

    exit_code = _run_cli(
        db_session, ["label", "digest", "--count", "1"], monkeypatch, as_email=user.email
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "run_type" in out
    assert "outcome=themes_present" in out
    assert "[rank 1]" in out


def test_label_draft_smoke(db_session, user, monkeypatch, capsys):
    _seed_chain(db_session, user, n_posts=1)
    _scripted_input(monkeypatch, ["3", ""])

    exit_code = _run_cli(
        db_session, ["label", "draft", "--count", "1"], monkeypatch, as_email=user.email
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "draft_text" in out
    assert "theme summary" in out


def test_label_cluster_smoke(db_session, user, monkeypatch, capsys):
    _seed_chain(db_session, user, n_posts=2)
    _scripted_input(monkeypatch, ["y", ""])

    exit_code = _run_cli(
        db_session, ["label", "cluster", "--count", "1"], monkeypatch, as_email=user.email
    )

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "member posts" in out
    assert "cluster_post_count" in out


# --- label: --id targeting ----------------------------------------------------


def test_label_with_id_targets_specific_item_ignoring_sampling(
    db_session, user, monkeypatch, capsys
):
    # Seed two chains so random sampling could pick either digest; --id must
    # deterministically hit the second one regardless.
    _seed_chain(db_session, user, n_posts=1)
    chain2 = _seed_chain(db_session, user, n_posts=1)
    _scripted_input(monkeypatch, ["5", ""])

    exit_code = _run_cli(
        db_session,
        ["label", "digest", "--id", str(chain2["digest"].id)],
        monkeypatch,
        as_email=user.email,
    )

    assert exit_code == 0
    labels = db_session.execute(select(EvaluationLabel)).scalars().all()
    assert len(labels) == 1
    assert labels[0].target_id == chain2["digest"].id
    assert labels[0].label_type == "5"
    assert "Labeled 1/1" in capsys.readouterr().out


def test_label_with_id_rejects_unknown_id(db_session, user, monkeypatch, capsys):
    _seed_chain(db_session, user, n_posts=1)
    missing_id = "00000000-0000-0000-0000-000000000000"

    exit_code = _run_cli(
        db_session, ["label", "digest", "--id", missing_id], monkeypatch, as_email=user.email
    )

    assert exit_code == 1
    assert f"No 'digest' item with id {missing_id} found." in capsys.readouterr().err
    assert db_session.execute(select(EvaluationLabel)).scalars().all() == []


def test_label_with_id_rejects_already_labeled_item(db_session, user, monkeypatch, capsys):
    chain = _seed_chain(db_session, user, n_posts=1)
    digest_id = chain["digest"].id
    _scripted_input(monkeypatch, ["5", ""])
    _run_cli(
        db_session,
        ["label", "digest", "--id", str(digest_id)],
        monkeypatch,
        as_email=user.email,
    )
    capsys.readouterr()  # discard first run's output

    exit_code = _run_cli(
        db_session,
        ["label", "digest", "--id", str(digest_id)],
        monkeypatch,
        as_email=user.email,
    )

    assert exit_code == 1
    assert (
        f"'digest' item {digest_id} was already labeled by this user."
        in capsys.readouterr().err
    )
    assert len(db_session.execute(select(EvaluationLabel)).scalars().all()) == 1


def test_label_with_id_rejects_item_owned_by_other_user(
    db_session, user, other_user, monkeypatch, capsys
):
    chain = _seed_chain(db_session, user, n_posts=1)

    exit_code = _run_cli(
        db_session,
        ["label", "digest", "--id", str(chain["digest"].id)],
        monkeypatch,
        as_email=other_user.email,
    )

    assert exit_code == 1
    assert (
        f"No 'digest' item with id {chain['digest'].id} found." in capsys.readouterr().err
    )
    assert db_session.execute(select(EvaluationLabel)).scalars().all() == []


def test_label_with_id_rejects_malformed_uuid(db_session, user, monkeypatch, capsys):
    _seed_chain(db_session, user, n_posts=1)

    exit_code = _run_cli(
        db_session, ["label", "digest", "--id", "not-a-uuid"], monkeypatch, as_email=user.email
    )

    assert exit_code == 1
    assert "--id must be a valid UUID" in capsys.readouterr().err
    assert db_session.execute(select(EvaluationLabel)).scalars().all() == []


# --- report -------------------------------------------------------------------


def test_report_computes_accuracy_and_average(db_session, user, monkeypatch, capsys):
    _seed_chain(db_session, user, n_posts=2)
    _scripted_input(monkeypatch, ["y", "", "n", ""])
    _run_cli(db_session, ["label", "filter", "--count", "2"], monkeypatch, as_email=user.email)

    _seed_chain(db_session, user, n_posts=1)
    _scripted_input(monkeypatch, ["4", ""])
    _run_cli(db_session, ["label", "summarize", "--count", "1"], monkeypatch, as_email=user.email)

    exit_code = _run_cli(db_session, ["report"], monkeypatch, as_email=user.email)

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "accuracy=50.0% (1/2)" in out
    assert "avg_rating=4.00 (n=1)" in out
    assert "no labels yet" in out  # e.g. cluster/detect/draft/digest untouched


def test_report_stage_filter_shows_only_that_stage(db_session, user, monkeypatch, capsys):
    _seed_chain(db_session, user, n_posts=1)
    _scripted_input(monkeypatch, ["y", ""])
    _run_cli(db_session, ["label", "filter", "--count", "1"], monkeypatch, as_email=user.email)
    capsys.readouterr()  # discard the label command's own output

    exit_code = _run_cli(
        db_session, ["report", "--stage", "filter"], monkeypatch, as_email=user.email
    )

    assert exit_code == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 1
    assert lines[0].startswith("filter")


def test_report_is_scoped_per_user(db_session, user, other_user, monkeypatch, capsys):
    _seed_chain(db_session, user, n_posts=1)
    _scripted_input(monkeypatch, ["y", ""])
    _run_cli(db_session, ["label", "filter", "--count", "1"], monkeypatch, as_email=user.email)

    exit_code = _run_cli(
        db_session, ["report", "--stage", "filter"], monkeypatch, as_email=other_user.email
    )

    assert exit_code == 0
    assert "no labels yet" in capsys.readouterr().out
