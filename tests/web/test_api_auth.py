"""Tests for `src/web/routers/auth.py` — real per-user login (specs/003-web-dashboard,
User Story 5 / FR-015), replacing the dashboard's original single shared password.
"""

from __future__ import annotations

from src.models.user import User
from src.utils.password import hash_password, verify_password
from src.web.auth import verify_user_password
from tests.web.conftest import TEST_USER_PASSWORD


def test_me_is_unauthenticated_before_any_login(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "email": None}


def test_login_with_unknown_email_is_rejected(client):
    response = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert response.status_code == 401

    assert client.get("/api/auth/me").json() == {"authenticated": False, "email": None}


def test_login_with_wrong_password_is_rejected(client, seed_user):
    response = client.post(
        "/api/auth/login", json={"email": seed_user.email, "password": "definitely-wrong"}
    )
    assert response.status_code == 401
    assert client.get("/api/auth/me").json() == {"authenticated": False, "email": None}


def test_login_for_a_user_with_no_password_hash_yet_is_rejected(client, db_session):
    """A CLI-only account that `user create` has never been run for
    (password_hash is None) must reject every login attempt, never crash."""
    user = User(email="cli-only@example.com", x_account_handle="cli_only")
    db_session.add(user)
    db_session.commit()

    response = client.post("/api/auth/login", json={"email": user.email, "password": "anything"})
    assert response.status_code == 401


def test_login_with_correct_credentials_authenticates_the_session(client, seed_user):
    response = client.post(
        "/api/auth/login", json={"email": seed_user.email, "password": TEST_USER_PASSWORD}
    )
    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "email": seed_user.email}

    assert client.get("/api/auth/me").json() == {"authenticated": True, "email": seed_user.email}


def test_unknown_email_and_wrong_password_give_the_identical_error(client, seed_user):
    """No user-enumeration: a login attempt must never reveal whether the
    email or the password was the wrong part."""
    unknown_email_response = client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "x"}
    )
    wrong_password_response = client.post(
        "/api/auth/login", json={"email": seed_user.email, "password": "wrong"}
    )
    assert unknown_email_response.status_code == wrong_password_response.status_code == 401
    assert unknown_email_response.json()["detail"] == wrong_password_response.json()["detail"]


def test_logout_clears_the_session(authed_client, seed_user):
    assert authed_client.get("/api/auth/me").json() == {
        "authenticated": True,
        "email": seed_user.email,
    }

    response = authed_client.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"authenticated": False, "email": None}
    assert authed_client.get("/api/auth/me").json() == {"authenticated": False, "email": None}


def test_protected_endpoint_401s_without_a_login(client):
    response = client.get("/api/topics")
    assert response.status_code == 401


def test_protected_endpoint_succeeds_after_login(authed_client, seed_user):
    response = authed_client.get("/api/topics")
    assert response.status_code == 200
    assert response.json() == []


def test_me_self_heals_when_the_logged_in_user_no_longer_exists(
    authed_client, seed_user, db_session
):
    assert authed_client.get("/api/auth/me").json()["authenticated"] is True

    db_session.delete(seed_user)
    db_session.commit()

    assert authed_client.get("/api/auth/me").json() == {"authenticated": False, "email": None}


def test_protected_endpoint_self_heals_when_the_logged_in_user_no_longer_exists(
    authed_client, seed_user, db_session
):
    assert authed_client.get("/api/topics").status_code == 200

    db_session.delete(seed_user)
    db_session.commit()

    assert authed_client.get("/api/topics").status_code == 401


def test_verify_user_password_rejects_when_password_hash_is_none():
    user = User(email="x@example.com", x_account_handle="x", password_hash=None)
    assert verify_user_password(user, "anything") is False


def test_verify_user_password_round_trips_with_hash_password():
    user = User(email="x@example.com", x_account_handle="x", password_hash=hash_password("s3cret"))
    assert verify_user_password(user, "s3cret") is True
    assert verify_user_password(user, "wrong") is False


def test_hash_password_never_stores_the_plaintext():
    hashed = hash_password("s3cret")
    assert hashed != "s3cret"
    assert verify_password("s3cret", hashed) is True
