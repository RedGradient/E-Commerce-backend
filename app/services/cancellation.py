from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app import messaging
from app.models import Order, OrderStatus
from app.services.checkout import OrderNotFound


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
        order = await session.get(Order, order_id)
        if order is None:
            raise OrderNotFound()

        if order.status == OrderStatus.Cancelled:
            raise OrderAlreadyCancelled()

        if order.status != OrderStatus.Created:
            raise OrderNotCancellable()

        order.status = OrderStatus.Cancelled
        order.cancelled_at = datetime.now(UTC)
        order.cancel_reason = reason
        session.add(order)
        await session.commit()
        await session.refresh(order)

        payload = {
            "order_id": order.id,
            "status": order.status.value,
            "cancelled_at": order.cancelled_at.isoformat(),
            "cancel_reason": order.cancel_reason,
        }
        await messaging.publish_order_cancelled(payload)
        return payload
