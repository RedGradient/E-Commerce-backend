import logging
from datetime import datetime
from typing import Any

import stripe
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.order_state_machine import is_refund_allowed
from app.logging_context import log_context, log_extra
from app.models.models import Order, OrderStatus
from app.services.checkout import OrderNotFound

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
    def __init__(self, stripe_client: stripe.StripeClient | None = None) -> None:
        self._stripe = stripe_client or stripe.StripeClient(
            api_key=settings.stripe_api_key
        )

    async def refund(self, order_id: int, session: AsyncSession) -> dict:
        with log_context(order_id=order_id):
            order = await session.get(Order, order_id)
            order = verify_order_can_be_refunded(order)
            payment_intent_id = order.payment_intent_id

            try:
                refund = await self._stripe.v1.refunds.create_async(
                    params={
                        "payment_intent": payment_intent_id,
                        "reason": "requested_by_customer",
                    },  # type: ignore
                    options={"idempotency_key": f"refund-order-{order.id}"},
                )
            except stripe.StripeError as err:
                logger.error(
                    "Stripe refund failed",
                    extra=log_extra(
                        event="refund.stripe_failed",
                        payment_intent_id=payment_intent_id,
                        error=str(err),
                    ),
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
