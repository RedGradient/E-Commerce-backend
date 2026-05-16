from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import (
    get_idempotency_result,
    release_idempotency_key,
    reserve_idempotency,
    save_idempotency_result,
)
from app.integrations.stripe_client import (
    StripeClient,
    StripePaymentError,
    StripePaymentIntent,
)
from app.models.models import Order, OrderStatus


class OrderNotPayable(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class OrderNotFound(Exception):
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
        # Return data if order already processed
        if cached := await read_idempotency(idempotency_key):
            return cached

        order = await session.get(Order, order_id)
        order = validate_order(order)

        # Raise an error if idempotency key already exists in Redis
        if not await reserve_idempotency(idempotency_key):
            if cached := await read_idempotency(idempotency_key):
                return cached
            raise IdempotencyInProgress()

        try:
            payment_intent = await self._charge(order, idempotency_key)

            order.status = OrderStatus.Processing
            order.payment_intent_id = payment_intent.id
            await session.flush()
        except StripePaymentError as err:
            await release_idempotency_key(idempotency_key)
            raise PaymentFailed() from err

        await session.commit()

        payload = build_checkout_payload(order)
        await save_idempotency_result(idempotency_key, payload)

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
    if order.status not in {OrderStatus.Created, OrderStatus.Processing}:
        raise OrderNotPayable()
    return order


def build_checkout_payload(order: Order) -> dict[str, Any]:
    return {
        "order_id": order.id,
        "payment_intent_id": order.payment_intent_id,
        "status": order.status.value,
        "amount": str(order.total_price),
        "currency": "usd",
        # "paid_at": order.paid_at.isoformat() if order.paid_at else None,
    }


async def read_idempotency(key: str) -> dict | None:
    res = await get_idempotency_result(key)
    if res is None:
        return None  # ключа нет — продолжаем checkout
    if res["status"] == "completed":
        return res["payload"]  # готовый ответ
    raise IdempotencyInProgress()  # processing — как в твоих блоках
