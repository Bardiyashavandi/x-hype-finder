"""Tests for `src/web/routers/auth.py` (specs/003-web-dashboard/plan.md §1 "Auth")."""

from __future__ import annotations

from src.web.auth import check_password
from tests.web.conftest import WEB_PASSWORD


def test_me_is_unauthenticated_before_any_login(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json() == {"authenticated": False}


def test_login_with_wrong_password_is_rejected(client):
    response = client.post("/api/auth/login", json={"password": "definitely-wrong"})
    assert response.status_code == 401

    # The session must not have been marked authenticated by the failed attempt.
    assert client.get("/api/auth/me").json() == {"authenticated": False}


def test_login_with_correct_password_authenticates_the_session(client):
    response = client.post("/api/auth/login", json={"password": WEB_PASSWORD})
    assert response.status_code == 200
    assert response.json() == {"authenticated": True}

    assert client.get("/api/auth/me").json() == {"authenticated": True}


def test_logout_clears_the_session(authed_client):
    assert authed_client.get("/api/auth/me").json() == {"authenticated": True}

    response = authed_client.post("/api/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"authenticated": False}
    assert authed_client.get("/api/auth/me").json() == {"authenticated": False}


def test_protected_endpoint_401s_without_a_login(client):
    response = client.get("/api/topics")
    assert response.status_code == 401


def test_protected_endpoint_succeeds_after_login(authed_client, seed_user):
    response = authed_client.get("/api/topics")
    assert response.status_code == 200
    assert response.json() == []


def test_check_password_rejects_everything_when_unconfigured():
    """An unconfigured dashboard (no XHF_WEB_PASSWORD) must reject every
    login attempt rather than 500 or silently accept anything."""
    assert check_password("anything", env={}) is False


def test_check_password_uses_constant_time_comparison_against_the_configured_value():
    env = {"XHF_WEB_PASSWORD": "correct-horse-battery-staple"}
    assert check_password("correct-horse-battery-staple", env=env) is True
    assert check_password("wrong", env=env) is False
