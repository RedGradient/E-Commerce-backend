# ruff: noqa: E501
"""init schema

Revision ID: e4f8c2a91b03
Revises:
Create Date: 2026-06-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e4f8c2a91b03"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "Created",
                "Processing",
                "Paid",
                "Cancelled",
                "Refunded",
                name="orderstatus",
            ),
            server_default=sa.text("'Created'"),
            nullable=False,
        ),
        sa.Column("payment_intent_id", sa.String(), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=150), nullable=True),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "order_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "outbox",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("dedup_key", sa.String(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "attempts",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outbox_pending_id",
        "outbox",
        ["id"],
        unique=False,
        postgresql_where=sa.text("published_at IS NULL AND failed_at IS NULL"),
    )
    op.create_index("uq_outbox_dedup_key", "outbox", ["dedup_key"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_outbox_dedup_key", table_name="outbox")
    op.drop_index(
        "ix_outbox_pending_id",
        table_name="outbox",
        postgresql_where=sa.text("published_at IS NULL AND failed_at IS NULL"),
    )
    op.drop_table("outbox")
    op.drop_table("order_items")
    op.drop_table("products")
    op.drop_table("orders")
    sa.Enum(name="orderstatus").drop(op.get_bind(), checkfirst=True)
