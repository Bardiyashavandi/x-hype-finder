"""Unit tests for `user create` (src/cli/user.py) — the only way a web
dashboard account is ever provisioned (specs/003-web-dashboard, User Story
5 / FR-015).
"""

from __future__ import annotations

from contextlib import contextmanager

import pytest
from sqlalchemy import select

import src.cli.user as user_cli
from src.models.user import User
from src.utils.password import verify_password


def _run_cli(db_session, argv: list[str], monkeypatch, *, password: str | None) -> int:
    @contextmanager
    def fake_get_session():
        yield db_session

    monkeypatch.setattr(user_cli, "get_session", fake_get_session)

    if password is None:

        def raise_eof(prompt=""):
            raise EOFError

        monkeypatch.setattr(user_cli.getpass, "getpass", raise_eof)
    else:
        monkeypatch.setattr(user_cli.getpass, "getpass", lambda prompt="": password)

    return user_cli.main(argv)


def test_creating_a_new_user_without_handle_is_rejected(db_session, monkeypatch, capsys):
    exit_code = _run_cli(db_session, ["create", "new@example.com"], monkeypatch, password="s3cret")

    assert exit_code == 1
    assert "--handle" in capsys.readouterr().err
    assert db_session.execute(select(User)).scalars().all() == []


def test_creating_a_new_user_with_handle_hashes_the_password(db_session, monkeypatch):
    exit_code = _run_cli(
        db_session,
        ["create", "new@example.com", "--handle", "new_handle"],
        monkeypatch,
        password="s3cret",
    )

    assert exit_code == 0
    user = db_session.execute(select(User).where(User.email == "new@example.com")).scalar_one()
    assert user.x_account_handle == "new_handle"
    assert user.password_hash is not None
    assert user.password_hash != "s3cret"  # never stored in plaintext
    assert verify_password("s3cret", user.password_hash) is True


def test_creating_an_existing_user_without_handle_only_updates_the_password(
    db_session, monkeypatch
):
    existing = User(email="pilot@example.com", x_account_handle="orig_handle")
    db_session.add(existing)
    db_session.commit()

    exit_code = _run_cli(
        db_session, ["create", "pilot@example.com"], monkeypatch, password="new-password"
    )

    assert exit_code == 0
    db_session.refresh(existing)
    assert existing.x_account_handle == "orig_handle"
    assert verify_password("new-password", existing.password_hash) is True


def test_creating_an_existing_user_with_handle_updates_both(db_session, monkeypatch):
    existing = User(email="pilot@example.com", x_account_handle="orig_handle")
    db_session.add(existing)
    db_session.commit()

    exit_code = _run_cli(
        db_session,
        ["create", "pilot@example.com", "--handle", "new_handle"],
        monkeypatch,
        password="new-password",
    )

    assert exit_code == 0
    db_session.refresh(existing)
    assert existing.x_account_handle == "new_handle"
    assert verify_password("new-password", existing.password_hash) is True


def test_empty_password_is_rejected_and_nothing_is_created(db_session, monkeypatch, capsys):
    exit_code = _run_cli(
        db_session,
        ["create", "new@example.com", "--handle", "new_handle"],
        monkeypatch,
        password="   ",
    )

    assert exit_code == 1
    assert "Password" in capsys.readouterr().err
    assert db_session.execute(select(User)).scalars().all() == []


def test_eof_on_password_prompt_aborts_without_mutating(db_session, monkeypatch, capsys):
    exit_code = _run_cli(
        db_session,
        ["create", "new@example.com", "--handle", "new_handle"],
        monkeypatch,
        password=None,
    )

    assert exit_code == 1
    assert "aborted" in capsys.readouterr().err.lower()
    assert db_session.execute(select(User)).scalars().all() == []


@pytest.mark.parametrize("bad_email", ["", "   "])
def test_empty_email_is_rejected(db_session, monkeypatch, bad_email):
    exit_code = _run_cli(
        db_session,
        ["create", bad_email, "--handle", "new_handle"],
        monkeypatch,
        password="s3cret",
    )

    assert exit_code == 1
    assert db_session.execute(select(User)).scalars().all() == []
