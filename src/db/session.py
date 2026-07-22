"""SQLAlchemy engine and session management (tasks.md T006).

The database file location is app config, not a credential (Constitution V /
FR-021 govern external-service secrets only), so it is read directly from an
optional env var here rather than through src/config.py's fail-fast credential
loader (T021).
"""

from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Shared declarative base for every model in src/models/."""


def _default_database_url() -> str:
    data_dir = Path(os.environ.get("XHF_DATA_DIR", ".data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{data_dir / 'xhf.db'}"


def get_engine():
    database_url = os.environ.get("XHF_DATABASE_URL", _default_database_url())
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args)


engine = get_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Session:
    """Return a new Session. Callers own its lifecycle (use as a context manager)."""
    return SessionLocal()
