from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import (
    get_idempotency_result,
    release_idempotency_key,
    save_idempotency_result,
    try_reserve_idempotency_key,
)
from app.integrations.stripe_client import StripeClient, StripePaymentError
from app.models.models import Order, OrderStatus
from app.models.outbox import Outbox


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
        res = await get_idempotency_result(idempotency_key)
        if res is not None:
            if res["status"] == "completed":
                return res["payload"]
            raise IdempotencyInProgress()

        order = await session.get(Order, order_id)
        if order is None:
            raise OrderNotFound()
        if order.status not in {OrderStatus.Created, OrderStatus.Processing}:
            raise OrderNotPayable()

        # Raise an error if idempotency key already exists in Redis
        if not await try_reserve_idempotency_key(idempotency_key):
            res = await get_idempotency_result(idempotency_key)
            if res is not None and res["status"] == "completed":
                return res["payload"]
            raise IdempotencyInProgress()

        try:
            order.status = OrderStatus.Processing
            session.add(order)
            await session.flush()

            payment_intent = await self._stripe.create_payment_intent(
                order.total_price,
                idempotency_key,
                currency="usd",
                metadata={"order_id": str(order.id)},
            )
        except StripePaymentError as err:
            await release_idempotency_key(idempotency_key)
            raise PaymentFailed() from err

        # async with session.begin():
        # Set order's payment-related fields
        order.status = OrderStatus.Paid
        order.payment_intent_id = payment_intent.id
        paid_at = datetime.now(UTC)
        order.paid_at = paid_at
        session.add(order)

        # Prepare and save payment result
        payload = {
            "order_id": order.id,
            "payment_intent_id": payment_intent.id,
            "status": order.status.value,
            "amount": str(order.total_price),
            "currency": "usd",
            "paid_at": paid_at.isoformat(),
        }

        # Create outbox message
        outbox_message = Outbox(
            event_type="order.paid", order_id=order.id, payload=payload
        )
        session.add(outbox_message)

        await session.commit()

        await save_idempotency_result(
            idempotency_key,
            payload,
        )

        return payload
