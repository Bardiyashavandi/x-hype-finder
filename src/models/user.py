"""User model (tasks.md T008, data-model.md § User).

Represents one of the two MVP users (FR-015, User Story 5). Every other table
is ultimately owned by a User, directly or transitively via foreign key — see
src/db/scoped.py for how that ownership is enforced on queries.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from src.db.session import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    x_account_handle: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), nullable=False)
