"""Unit tests for per-user X credential loading (tasks.md T067, FR-015, FR-021).

`load_x_credentials_for_user` is the piece that keeps two users' X OAuth
credentials from ever colliding: each user's credentials live behind an
env-var namespace derived from their own `x_account_handle`, with no
shared/unnamespaced fallback to accidentally fall through to.
"""

from __future__ import annotations

import uuid

import pytest

from src.config import ConfigError, load_x_credentials_for_user
from src.models.user import User


def _user(handle: str) -> User:
    return User(id=uuid.uuid4(), email=f"{handle}@example.com", x_account_handle=handle)


def test_loads_credentials_namespaced_by_the_users_own_handle():
    env = {
        "X_API_KEY__PILOT": "key-a",
        "X_API_SECRET__PILOT": "secret-a",
        "X_ACCESS_TOKEN__PILOT": "token-a",
        "X_ACCESS_TOKEN_SECRET__PILOT": "token-secret-a",
    }

    creds = load_x_credentials_for_user(_user("pilot"), env=env)

    assert creds.api_key == "key-a"
    assert creds.api_secret == "secret-a"
    assert creds.access_token == "token-a"
    assert creds.access_token_secret == "token-secret-a"


def test_non_alphanumeric_handles_are_normalized_to_a_safe_env_var_namespace():
    env = {
        "X_API_KEY__PILOT_TWO": "key-b",
        "X_API_SECRET__PILOT_TWO": "secret-b",
        "X_ACCESS_TOKEN__PILOT_TWO": "token-b",
        "X_ACCESS_TOKEN_SECRET__PILOT_TWO": "token-secret-b",
    }

    creds = load_x_credentials_for_user(_user("pilot-two"), env=env)

    assert creds.api_key == "key-b"


def test_two_users_resolve_to_fully_independent_credentials():
    """The core isolation guarantee (User Story 5, spec.md Acceptance Scenario 2):
    User B's env has no access to User A's credentials, and vice versa."""
    env = {
        "X_API_KEY__PILOT": "key-a",
        "X_API_SECRET__PILOT": "secret-a",
        "X_ACCESS_TOKEN__PILOT": "token-a",
        "X_ACCESS_TOKEN_SECRET__PILOT": "token-secret-a",
        "X_API_KEY__SECOND": "key-b",
        "X_API_SECRET__SECOND": "secret-b",
        "X_ACCESS_TOKEN__SECOND": "token-b",
        "X_ACCESS_TOKEN_SECRET__SECOND": "token-secret-b",
    }

    creds_a = load_x_credentials_for_user(_user("pilot"), env=env)
    creds_b = load_x_credentials_for_user(_user("second"), env=env)

    assert creds_a.api_key != creds_b.api_key
    assert creds_a.access_token_secret != creds_b.access_token_secret


def test_missing_namespaced_credentials_fails_fast_with_no_shared_fallback():
    """A user with no dedicated credentials configured must never silently
    fall back to some other shared/default set (that would be the exact
    cross-user leak FR-015 forbids) — it must fail loudly instead."""
    env = {
        "X_API_KEY__OTHERUSER": "key-a",
        "X_API_SECRET__OTHERUSER": "secret-a",
        "X_ACCESS_TOKEN__OTHERUSER": "token-a",
        "X_ACCESS_TOKEN_SECRET__OTHERUSER": "token-secret-a",
    }

    with pytest.raises(ConfigError, match="pilot"):
        load_x_credentials_for_user(_user("pilot"), env=env)


def test_missing_credentials_error_names_the_exact_missing_vars():
    with pytest.raises(ConfigError) as exc_info:
        load_x_credentials_for_user(_user("pilot"), env={})

    message = str(exc_info.value)
    assert "X_API_KEY__PILOT" in message
    assert "X_API_SECRET__PILOT" in message
    assert "X_ACCESS_TOKEN__PILOT" in message
    assert "X_ACCESS_TOKEN_SECRET__PILOT" in message
