"""Refine Channel/Viewer presence tracking; add diagnostic fields

Revision ID: b7046f0b0dfa
Revises:
Create Date: 2026-03-16 15:22:39.607740

"""
from typing import Sequence, Union

# alembic imports
from alembic import op
import sqlalchemy as sa

# custom imports
import app.db.types

# additional imports


# revision identifiers, used by Alembic.
revision: str = 'b7046f0b0dfa'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""

    # ---- Channel changes ----

    # Rename fields
    op.alter_column("channels", "live_at", new_column_name="live_started_at")
    op.alter_column("channels", "offline_at", new_column_name="last_offline_at")

    # New columns
    op.add_column("channels", sa.Column("cur_stream_id", sa.String(length=36), nullable=True))
    op.add_column("channels", sa.Column("prev_stream_id", sa.String(length=36), nullable=True))
    op.add_column("channels", sa.Column("is_live", sa.Boolean(), nullable=False, server_default=sa.false()))

    # ---- Viewer changes ----

    # Rename fields
    op.alter_column("viewers", "joined_at", new_column_name="presence_started_at")
    op.alter_column("viewers", "left_at", new_column_name="last_left_at")
    op.alter_column("viewers", "join_count", new_column_name="active_session_count")

    # New columns
    op.add_column("viewers", sa.Column("last_streak_stream_id", sa.String(length=36), nullable=True))

    # Special case: `watch_streak`
    # It becomes `total_streams_watched` because it behaved like it by error.
    # Then we add `cur_watch_streak` to replace and reset it.
    op.alter_column("viewers", "watch_streak", new_column_name="total_streams_watched")
    op.add_column("viewers", sa.Column("cur_watch_streak", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    """Downgrade schema."""

    # ---- Viewer revert ----

    # Remove new columns
    op.drop_column("viewers", "last_streak_stream_id")

    # Revert special case: `watch_streak`
    op.drop_column("viewers", "cur_watch_streak")
    op.alter_column("viewers", "total_streams_watched", new_column_name="watch_streak")

    # Restore renamed presence fields
    op.alter_column("viewers", "active_session_count", new_column_name="join_count")
    op.alter_column("viewers", "last_left_at", new_column_name="left_at")
    op.alter_column("viewers", "presence_started_at", new_column_name="joined_at")

    # ---- Channel revert ----

    # Remove new columns
    op.drop_column("channels", "is_live")
    op.drop_column("channels", "prev_stream_id")
    op.drop_column("channels", "cur_stream_id")

    # Restore renamed fields
    op.alter_column("channels", "last_offline_at", new_column_name="offline_at")
    op.alter_column("channels", "live_started_at", new_column_name="live_at")
