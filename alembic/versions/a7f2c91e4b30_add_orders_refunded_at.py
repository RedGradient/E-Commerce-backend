"""add orders.refunded_at

Revision ID: a7f2c91e4b30
Revises: 310b40a77650
Create Date: 2026-05-20 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7f2c91e4b30"
down_revision: str | None = "310b40a77650"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "refunded_at")
