"""add Outbox.dedup_key

Revision ID: 9b9e7cd9154d
Revises: a7f2c91e4b30
Create Date: 2026-05-27 17:24:47.977194

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9b9e7cd9154d"
down_revision: str | None = "a7f2c91e4b30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("outbox", sa.Column("dedup_key", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE outbox
        SET dedup_key = event_type || ':' || order_id::text || ':' || id::text
        WHERE dedup_key IS NULL
        """
    )
    op.alter_column("outbox", "dedup_key", nullable=False)
    op.create_index("uq_outbox_dedup_key", "outbox", ["dedup_key"], unique=True)
    op.drop_index("uq_outbox_pending_order_event", table_name="outbox")


def downgrade() -> None:
    op.create_index(
        "uq_outbox_pending_order_event",
        "outbox",
        ["order_id", "event_type"],
        unique=True,
        postgresql_where=sa.text("published_at IS NULL AND failed_at IS NULL"),
    )
    op.drop_index("uq_outbox_dedup_key", table_name="outbox")
    op.drop_column("outbox", "dedup_key")
