"""add Refund to OrderStatus enum

Revision ID: 310b40a77650
Revises: 8315d4071357
Create Date: 2026-05-25 17:01:04.861520

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "310b40a77650"
down_revision: str | None = "1c55764f215e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'Refunded'")


def downgrade() -> None:
    pass
