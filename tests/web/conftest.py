"""Shared fixtures for tests/web/* — a FastAPI `TestClient` wired to the
same in-memory `db_session` fixture every other suite uses
(tests/conftest.py), with the DB-access dependencies overridden per
specs/003-web-dashboard/plan.md §5 ("DB dependency overridden to the
existing in-memory db_session fixture, Fetch/Claude mocked the same way
test_on_demand_digest.py/test_idea_validation_flow.py already do").
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from src.models.user import User
from src.utils.password import hash_password
from src.web.app import create_app
from src.web.deps import get_db, get_session_factory

# The password every `seed_user`-backed `User` row is given (User Story 5 /
# FR-015: real per-user login, specs/003-web-dashboard) — `authed_client`
# logs in with this against that same seeded account.
TEST_USER_PASSWORD = "correct-horse-battery-staple"
WEB_SESSION_SECRET = "test-dashboard-session-secret"


@pytest.fixture()
def app(db_session, monkeypatch):
    monkeypatch.setenv("XHF_WEB_SESSION_SECRET", WEB_SESSION_SECRET)
    application = create_app()

    def _override_get_db():
        yield db_session

    @contextmanager
    def _fake_session():
        # Same "yield the test's own db_session, never close it" convention
        # tests/integration/test_on_demand_digest.py's `fake_get_session`
        # uses — the background-job worker functions use this exactly like
        # `with get_session() as session:` in src/cli/*.py.
        yield db_session

    def _override_get_session_factory():
        return _fake_session

    application.dependency_overrides[get_db] = _override_get_db
    application.dependency_overrides[get_session_factory] = _override_get_session_factory

    return application


@pytest.fixture()
def client(app):
    return TestClient(app)


@pytest.fixture()
def seed_user(db_session) -> User:
    """The one `User` most tests act as — a real dashboard account (a
    bcrypt hash of `TEST_USER_PASSWORD`), the same account `authed_client`
    logs in as."""
    user = User(
        email="pilot@example.com",
        x_account_handle="pilot",
        password_hash=hash_password(TEST_USER_PASSWORD),
        created_at=datetime.now(UTC),
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def authed_client(client, seed_user):
    """A `client` that has already logged in as `seed_user` — its session
    cookie carries that user's real id for every subsequent request
    (TestClient persists cookies across calls)."""
    response = client.post(
        "/api/auth/login", json={"email": seed_user.email, "password": TEST_USER_PASSWORD}
    )
    assert response.status_code == 200
    return client
