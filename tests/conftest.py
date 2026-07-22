import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.models  # noqa: F401 - populates Base.metadata for create_all below
from src.db.session import Base


@pytest.fixture()
def db_engine():
    """A fresh in-memory SQLite engine, isolated per test, with every model's
    table created (src.models' import registers them all on Base.metadata)."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(db_engine):
    session_factory = sessionmaker(bind=db_engine)
    session = session_factory()
    yield session
    session.close()
