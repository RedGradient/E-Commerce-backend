from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (
        # Воркер: WHERE published_at IS NULL AND failed_at IS NULL ORDER BY id
        # Ускоряет получение pending сообщений в workers.outbox_publisher
        Index(
            "ix_outbox_pending_id",
            "id",
            postgresql_where=text("published_at IS NULL AND failed_at IS NULL"),
        ),
        # Дедуп: не должно быть записей с одним и тем же dedup_key
        # Это нужно для того, чтобы предотвратить повторную отправку сообщения в очередь
        Index(
            "uq_outbox_dedup_key",
            "dedup_key",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    dedup_key: Mapped[str] = mapped_column(String, nullable=False)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("orders.id", ondelete="CASCADE"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    attempts: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
        server_default=text("0"),
    )
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
