from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.models import Order, OrderItem, OrderStatus
from app.services.checkout import (
    IdempotencyInProgress,
    OrderNotPayable,
    build_checkout_payload,
    read_idempotency,
    validate_order,
)
from app.services.orders import OrderNotFound

# --- pure helpers ---


def test_validate_order_raises_when_missing() -> None:
    with pytest.raises(OrderNotFound):
        validate_order(None)


def test_validate_order_raises_when_not_payable() -> None:
    with pytest.raises(OrderNotPayable):
        validate_order(Order(status=OrderStatus.Paid))


def test_validate_order_accepts_created_and_processing() -> None:
    order = validate_order(Order(status=OrderStatus.Created))
    assert order.status == OrderStatus.Created
    assert validate_order(Order(status=OrderStatus.Processing)).status == (
        OrderStatus.Processing
    )


def test_build_checkout_payload() -> None:
    order = Order(
        id=42,
        status=OrderStatus.Processing,
        payment_intent_id="pi_abc",
        items=[
            OrderItem(
                product_id=1,
                order_id=42,
                quantity=1,
                unit_price=Decimal("19.99"),
            )
        ],
    )

    assert build_checkout_payload(order) == {
        "order_id": 42,
        "payment_intent_id": "pi_abc",
        "status": "Processing",
        "amount": "19.99",
        "currency": "usd",
    }


@pytest.mark.asyncio
async def test_read_idempotency_returns_none_when_key_missing() -> None:
    with patch(
        "app.services.checkout.get_idempotency_result",
        new_callable=AsyncMock,
        return_value=None,
    ):
        assert await read_idempotency("key") is None


@pytest.mark.asyncio
async def test_read_idempotency_returns_payload_when_completed() -> None:
    cached = {"order_id": 1}
    with patch(
        "app.services.checkout.get_idempotency_result",
        new_callable=AsyncMock,
        return_value={"status": "completed", "payload": cached},
    ):
        assert await read_idempotency("key") == cached


@pytest.mark.asyncio
async def test_read_idempotency_raises_when_processing() -> None:
    with patch(
        "app.services.checkout.get_idempotency_result",
        new_callable=AsyncMock,
        return_value={"status": "processing"},
    ):
        with pytest.raises(IdempotencyInProgress):
            await read_idempotency("key")
