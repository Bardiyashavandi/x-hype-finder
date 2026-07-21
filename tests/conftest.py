import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def db_engine():
    """A fresh in-memory SQLite engine, isolated per test.

    Table creation is deferred to the Foundational phase (tasks.md T006-T017),
    once a shared model Base/metadata exists — this fixture only provides the
    connection plumbing tests can build on.
    """
    engine = create_engine("sqlite:///:memory:")
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    session_factory = sessionmaker(bind=db_engine)
    session = session_factory()
    yield session
    session.close()
