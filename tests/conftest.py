import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import src.models  # noqa: F401 - populates Base.metadata for create_all below
from src.db.session import Base


@pytest.fixture(autouse=True)
def _default_x_credentials(monkeypatch):
    """Most tests seed a single `User(x_account_handle="pilot")` (tests.md
    T067, src/config.py `load_x_credentials_for_user`) — set that user's
    namespaced X credential env vars by default so those tests don't each
    need to configure them, while still exercising the real per-user-namespaced
    lookup path rather than a shared/global fallback (there isn't one)."""
    monkeypatch.setenv("X_API_KEY__PILOT", "test-x-api-key")
    monkeypatch.setenv("X_API_SECRET__PILOT", "test-x-api-secret")
    monkeypatch.setenv("X_ACCESS_TOKEN__PILOT", "test-x-access-token")
    monkeypatch.setenv("X_ACCESS_TOKEN_SECRET__PILOT", "test-x-access-token-secret")


@pytest.fixture()
def db_engine():
    """A fresh in-memory SQLite engine, isolated per test, with every model's
    table created (src.models' import registers them all on Base.metadata).

    `StaticPool` + `check_same_thread=False` (mirroring src/db/session.py's
    own sqlite `connect_args`) so every session drawn from this engine shares
    one underlying connection regardless of which thread runs it — plain
    `:memory:` sqlite otherwise hands each thread its own separate, empty
    database (SQLAlchemy's default `SingletonThreadPool`), which breaks
    tests/web/*'s FastAPI `TestClient` (path operations run on a worker
    thread) the moment a request needs the same data the test set up."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    session_factory = sessionmaker(bind=db_engine)
    session = session_factory()
    yield session
    session.close()
