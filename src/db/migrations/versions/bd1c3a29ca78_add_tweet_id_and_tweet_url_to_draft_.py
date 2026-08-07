"""add tweet_id and tweet_url to draft_posts, widen status column

Revision ID: bd1c3a29ca78
Revises: 53dc8359af01
Create Date: 2026-08-07 16:42:02.322567

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bd1c3a29ca78'
down_revision: Union[str, Sequence[str], None] = '53dc8359af01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema.

    Widens `status` from VARCHAR(20) to VARCHAR(32) alongside adding the two
    new columns, in the same batch: the new PUBLISHED_MANUAL_OVERRIDE enum
    member (`src/models/draft_post.py`) is 25 chars, longer than the
    existing column. SQLite itself never enforces VARCHAR length, so this is
    a no-op there today, but the column width should still describe the
    actual data — this avoids a silent truncation trap if the app ever moves
    to a stricter backend (XHF_DATABASE_URL already supports non-SQLite
    URLs, per src/db/session.py).

    `batch_alter_table` is required here (not plain `op.add_column`/
    `op.alter_column`) because SQLite has no native ALTER COLUMN TYPE —
    batch mode recreates the table under the hood on that dialect and is a
    plain in-place ALTER on any dialect that does support it natively.
    """
    with op.batch_alter_table("draft_posts") as batch_op:
        batch_op.add_column(sa.Column("tweet_id", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("tweet_url", sa.String(), nullable=True))
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=20),
            type_=sa.String(length=32),
            existing_nullable=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("draft_posts") as batch_op:
        batch_op.alter_column(
            "status",
            existing_type=sa.String(length=32),
            type_=sa.String(length=20),
            existing_nullable=False,
        )
        batch_op.drop_column("tweet_url")
        batch_op.drop_column("tweet_id")
