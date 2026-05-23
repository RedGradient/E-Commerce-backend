from datetime import UTC, datetime

import pytest

from app.models.models import Order, OrderStatus
from app.services.cancellation import (
    OrderAlreadyCancelled,
    OrderNotCancellable,
    apply_cancellation,
    build_cancel_payload,
    verify_order_can_be_cancelled,
)
from app.services.checkout import OrderNotFound


def test_verify_order_can_be_cancelled_raises_when_missing() -> None:
    with pytest.raises(OrderNotFound):
        verify_order_can_be_cancelled(None)  # type: ignore[arg-type]


def test_verify_order_can_be_cancelled_raises_when_already_cancelled() -> None:
    order = Order(id=42, status=OrderStatus.Cancelled)
    with pytest.raises(OrderAlreadyCancelled):
        verify_order_can_be_cancelled(order)


def test_verify_order_can_be_cancelled_raises_when_paid() -> None:
    order = Order(id=42, status=OrderStatus.Paid)
    with pytest.raises(OrderNotCancellable):
        verify_order_can_be_cancelled(order)


def test_verify_order_can_be_cancelled_ok_for_created() -> None:
    order = Order(id=42, status=OrderStatus.Created)
    verify_order_can_be_cancelled(order)


def test_apply_cancellation_sets_fields() -> None:
    order = Order(id=42, status=OrderStatus.Created)
    apply_cancellation(order, "customer changed mind")

    assert order.status == OrderStatus.Cancelled
    assert order.cancel_reason == "customer changed mind"
    assert order.cancelled_at is not None
    assert order.cancelled_at.tzinfo is UTC


def test_build_cancel_payload() -> None:
    order = Order(id=42, status=OrderStatus.Cancelled, cancel_reason="x")
    at = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)

    payload = build_cancel_payload(order, cancelled_at=at)

    assert payload == {
        "order_id": 42,
        "status": "Cancelled",
        "cancelled_at": at.isoformat(),
        "cancel_reason": "x",
    }
