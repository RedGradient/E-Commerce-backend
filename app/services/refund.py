import logging
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.order_state_machine import is_refund_allowed
from app.integrations.stripe import StripeClient, StripePaymentError
from app.logging_context import log_context, log_extra
from app.models.models import Order, OrderStatus
from app.services.orders import OrderNotFound

logger = logging.getLogger(__name__)


class OrderNotRefundable(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class OrderAlreadyRefunded(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class RefundFailed(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class RefundService:
    def __init__(self, stripe_client: StripeClient | None = None) -> None:
        self._stripe = stripe_client or StripeClient()

    async def refund(self, order_id: int, session: AsyncSession) -> dict:
        with log_context(order_id=order_id):
            order = await session.get(Order, order_id)
            order = verify_order_can_be_refunded(order)
            payment_intent_id = order.payment_intent_id

            try:
                refund = await self._stripe.refund(
                    order_id=order.id,
                    payment_intent_id=payment_intent_id,  # type: ignore[arg-type]
                )
            except StripePaymentError as err:
                logger.warning(
                    "Refund request failed",
                    extra=log_extra(event="refund.failed", error=str(err)),
                )
                raise RefundFailed() from err

            logger.info(
                "Refund initiated",
                extra=log_extra(
                    event="refund.initiated",
                    payment_intent_id=payment_intent_id,
                    stripe_refund_id=refund.id,
                ),
            )
            return {
                "order_id": order.id,
                "status": order.status,
                "stripe_refund_id": refund.id,
                "message": "refund initiated; order status updates via webhook",
            }


def verify_order_can_be_refunded(order: Order | None) -> Order:
    if order is None:
        raise OrderNotFound()

    if order.status == OrderStatus.Refunded:
        raise OrderAlreadyRefunded()

    if not is_refund_allowed(order.status):
        raise OrderNotRefundable()

    if not order.payment_intent_id:
        raise OrderNotRefundable()

    return order


def build_refund_payload(order: Order, refunded_at: datetime) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "payment_intent_id": order.payment_intent_id,
        "status": order.status.value,
        "amount": str(order.total_price),
        "currency": "usd",
        "refunded_at": refunded_at.isoformat(),
    }
