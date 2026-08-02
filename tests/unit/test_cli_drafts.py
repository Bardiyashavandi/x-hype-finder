"""Unit tests for `drafts mark-published`'s confirmation gate
(src/cli/drafts.py).

`mark-published` never calls the X API — it only records that the caller
already posted a `held_manual` draft themselves. Because there is no tweet
id/URL captured anywhere to verify that, the only safeguard against
conflating "run this command" with "actually post to X" is an interactive
confirmation the caller must explicitly type through (or `--yes` to opt out
for scripting).
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest

import src.cli.drafts as drafts_cli
from src.models.draft_post import DraftPost, DraftPostStatus
from src.models.user import User


def _run_cli(db_session, argv: list[str], monkeypatch, *, as_email: str) -> int:
    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(drafts_cli, "get_session", fake_get_session)
    monkeypatch.setenv("XHF_USER_EMAIL", as_email)
    return drafts_cli.main(argv)


@pytest.fixture()
def user(db_session) -> User:
    u = User(email="pilot@example.com", x_account_handle="pilot")
    db_session.add(u)
    db_session.flush()
    return u


def _held_draft(user: User, *, confidence: int = 45) -> DraftPost:
    return DraftPost(
        theme_id=uuid.uuid4(),
        user_id=user.id,
        draft_text="A draft.",
        confidence_score=confidence,
        status=DraftPostStatus.HELD_MANUAL,
    )


def test_yes_flag_skips_prompt_and_publishes(db_session, user, monkeypatch, capsys):
    draft = _held_draft(user)
    db_session.add(draft)
    db_session.commit()

    def fail_if_called(_prompt=""):
        raise AssertionError("input() must not be called when --yes is passed")

    monkeypatch.setattr("builtins.input", fail_if_called)

    exit_code = _run_cli(
        db_session, ["mark-published", str(draft.id), "--yes"], monkeypatch, as_email=user.email
    )

    assert exit_code == 0
    db_session.refresh(draft)
    assert draft.status == DraftPostStatus.PUBLISHED_MANUAL
    assert draft.published_at is not None


def test_typing_yes_confirms_and_publishes(db_session, user, monkeypatch, capsys):
    draft = _held_draft(user)
    db_session.add(draft)
    db_session.commit()

    monkeypatch.setattr("builtins.input", lambda _prompt="": "yes")

    exit_code = _run_cli(
        db_session, ["mark-published", str(draft.id)], monkeypatch, as_email=user.email
    )

    assert exit_code == 0
    db_session.refresh(draft)
    assert draft.status == DraftPostStatus.PUBLISHED_MANUAL

    err = capsys.readouterr().err
    assert "does NOT" not in err  # that line lives in --help, not the prompt
    assert draft.draft_text in err
    assert "already posted it yourself" in err


@pytest.mark.parametrize("answer", ["", "no", "y", "YES please"])
def test_anything_other_than_exact_yes_aborts_without_mutating(
    db_session, user, monkeypatch, capsys, answer
):
    draft = _held_draft(user)
    db_session.add(draft)
    db_session.commit()

    monkeypatch.setattr("builtins.input", lambda _prompt="": answer)

    exit_code = _run_cli(
        db_session, ["mark-published", str(draft.id)], monkeypatch, as_email=user.email
    )

    assert exit_code == 1
    db_session.refresh(draft)
    assert draft.status == DraftPostStatus.HELD_MANUAL
    assert draft.published_at is None
    assert "Aborted" in capsys.readouterr().err


def test_eof_on_prompt_aborts_without_mutating(db_session, user, monkeypatch):
    draft = _held_draft(user)
    db_session.add(draft)
    db_session.commit()

    def raise_eof(_prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", raise_eof)

    exit_code = _run_cli(
        db_session, ["mark-published", str(draft.id)], monkeypatch, as_email=user.email
    )

    assert exit_code == 1
    db_session.refresh(draft)
    assert draft.status == DraftPostStatus.HELD_MANUAL


def test_non_held_manual_draft_errors_before_prompting(db_session, user, monkeypatch, capsys):
    draft = _held_draft(user)
    draft.status = DraftPostStatus.PUBLISHED_MANUAL
    db_session.add(draft)
    db_session.commit()

    def fail_if_called(_prompt=""):
        raise AssertionError("input() must not be called for a draft that can't be marked")

    monkeypatch.setattr("builtins.input", fail_if_called)

    exit_code = _run_cli(
        db_session, ["mark-published", str(draft.id)], monkeypatch, as_email=user.email
    )

    assert exit_code == 1
    assert "not 'held_manual'" in capsys.readouterr().err
