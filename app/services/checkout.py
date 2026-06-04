import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import (
    get_idempotency_result,
    release_idempotency_key,
    reserve_idempotency,
    save_idempotency_result,
)
from app.domain.order_state_machine import apply_start_payment, is_checkout_allowed
from app.integrations.stripe import (
    StripeClient,
    StripePaymentError,
    StripePaymentIntent,
)
from app.logging_context import log_context, log_extra
from app.models.models import Order
from app.services.orders import OrderNotFound

logger = logging.getLogger(__name__)


class OrderNotPayable(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class PaymentFailed(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class IdempotencyInProgress(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class CheckoutService:
    def __init__(
        self,
        stripe: StripeClient,
    ):
        self._stripe = stripe

    async def checkout(
        self,
        order_id: int,
        idempotency_key: str,
        session: AsyncSession,
    ) -> dict:
        with log_context(order_id=order_id, idempotency_key=idempotency_key):
            if cached := await read_idempotency(idempotency_key):
                logger.debug(
                    "Checkout idempotency cache hit",
                    extra=log_extra(event="checkout.idempotency_cache_hit"),
                )
                return cached

            order = await session.get(Order, order_id)
            order = validate_order(order)

            if not await reserve_idempotency(idempotency_key):
                if cached := await read_idempotency(idempotency_key):
                    return cached
                raise IdempotencyInProgress()

            try:
                payment_intent = await self._charge(order, idempotency_key)
                apply_start_payment(order, payment_intent_id=payment_intent.id)
                await session.flush()
            except StripePaymentError as err:
                await release_idempotency_key(idempotency_key)
                logger.warning(
                    "Checkout payment failed",
                    extra=log_extra(
                        event="checkout.payment_failed",
                        error=str(err),
                    ),
                )
                raise PaymentFailed() from err

            await session.commit()

            payload = build_checkout_payload(order)
            await save_idempotency_result(idempotency_key, payload)

            logger.info(
                "Checkout completed",
                extra=log_extra(
                    event="checkout.completed",
                    payment_intent_id=order.payment_intent_id,
                    order_status=order.status.value,
                ),
            )
            return payload

    async def _charge(self, order: Order, idempotency_key: str) -> StripePaymentIntent:
        return await self._stripe.create_payment_intent(
            order.total_price,
            idempotency_key,
            currency="usd",
            metadata={"order_id": str(order.id)},
        )


def validate_order(order: Order | None) -> Order:
    if order is None:
        raise OrderNotFound()
    if not is_checkout_allowed(order.status):
        raise OrderNotPayable()
    return order


def build_checkout_payload(order: Order) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "payment_intent_id": order.payment_intent_id,
        "status": order.status.value,
        "amount": str(order.total_price),
        "currency": "usd",
    }


async def read_idempotency(key: str) -> dict | None:
    res = await get_idempotency_result(key)
    if res is None:
        return None
    if res["status"] == "completed":
        return res["payload"]
    raise IdempotencyInProgress()
