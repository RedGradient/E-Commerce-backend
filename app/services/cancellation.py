import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_context import log_context, log_extra
from app.models.models import Order, OrderStatus
from app.models.outbox import Outbox
from app.services.checkout import OrderNotFound

logger = logging.getLogger(__name__)


class OrderAlreadyCancelled(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class OrderNotCancellable(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class CancellationService:
    async def cancel(
        self,
        order_id: int,
        session: AsyncSession,
        reason: str | None = None,
    ) -> dict:
        with log_context(order_id=order_id, cancel_reason=reason):
            order = await session.get(Order, order_id)
            verify_order_can_be_cancelled(order)

            apply_cancellation(order, reason)

            payload = build_cancel_payload(order, cancelled_at=datetime.now(UTC))
            session.add(
                Outbox(
                    event_type="order.cancelled",
                    order_id=order.id,  # type: ignore
                    payload=payload,
                )
            )

            await session.commit()

            logger.info(
                "Order cancelled",
                extra=log_extra(event="order.cancelled"),
            )
            return payload


def apply_cancellation(order: Order, reason: str | None) -> None:
    order.status = OrderStatus.Cancelled
    order.cancelled_at = datetime.now(UTC)
    order.cancel_reason = reason


def verify_order_can_be_cancelled(order: Order) -> None:
    if order is None:
        raise OrderNotFound()

    if order.status == OrderStatus.Cancelled:
        raise OrderAlreadyCancelled()

    if order.status != OrderStatus.Created:
        raise OrderNotCancellable()


def build_cancel_payload(order: Order, cancelled_at: datetime) -> dict:
    return {
        "order_id": order.id,
        "status": order.status.value,
        "cancelled_at": cancelled_at.isoformat(),
        "cancel_reason": order.cancel_reason,
    }
