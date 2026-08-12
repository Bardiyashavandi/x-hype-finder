"""add password_hash to users

Revision ID: 61e4315bcfe3
Revises: bd1c3a29ca78
Create Date: 2026-08-12 21:30:05.381512

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '61e4315bcfe3'
down_revision: Union[str, Sequence[str], None] = 'bd1c3a29ca78'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Adds `password_hash` for the web dashboard's per-user login (User Story 5 /
    FR-015 — real accounts replacing the single shared dashboard password,
    specs/003-web-dashboard). Nullable: existing CLI-only `User` rows have no
    password and simply can't log into the web dashboard until
    `python -m src.cli.user create` sets one for them — the CLI itself never
    reads this column (src/models/user.py).
    """
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("password_hash", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("password_hash")
