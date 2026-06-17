from collections.abc import Awaitable, Callable
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cache import get_idempotency_result
from app.integrations.stripe import StripeClient
from app.models.models import Order, OrderStatus
from app.services.checkout import CheckoutService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_checkout_ok(
    order_factory: Callable[..., Awaitable[Order]],
    db_session: AsyncSession,
):
    order = await order_factory(
        status=OrderStatus.Created,
        items=[
            {
                "product_name": "Test product",
                "description": "Description",
                "price": Decimal("27.50"),
                "quantity": 1,
            }
        ],
    )

    service = CheckoutService(StripeClient())
    payload = await service.checkout(
        order_id=order.id,
        idempotency_key="some-idempotency-key",
        session=db_session,
    )

    await db_session.refresh(order)

    assert payload == {
        "order_id": order.id,
        "payment_intent_id": order.payment_intent_id,
        "status": "Processing",
        "amount": "27.50",
        "currency": "usd",
    }

    assert order.status == OrderStatus.Processing
    assert order.payment_intent_id is not None
    assert order.payment_intent_id == payload["payment_intent_id"]
    assert order.paid_at is None

    cached = await get_idempotency_result("some-idempotency-key")
    assert cached is not None
    assert cached["status"] == "completed"
    assert cached["payload"] == payload


async def test_checkout_idempotency_cache(
    order_factory: Callable[..., Awaitable[Order]],
    db_session: AsyncSession,
):
    stripe_client = StripeClient()
    create_payment_intent_mock = AsyncMock(wraps=stripe_client.create_payment_intent)
    stripe_client.create_payment_intent = create_payment_intent_mock

    service = CheckoutService(stripe_client)

    order = await order_factory(
        status=OrderStatus.Created,
        items=[
            {
                "product_name": "Test product",
                "price": Decimal("10.00"),
                "quantity": 1,
            }
        ],
    )

    payload1 = await service.checkout(
        order_id=order.id,
        idempotency_key="the-idempotency-key",
        session=db_session,
    )

    payload2 = await service.checkout(
        order_id=order.id,
        idempotency_key="the-idempotency-key",
        session=db_session,
    )

    assert payload1 == payload2
    assert create_payment_intent_mock.await_count == 1
