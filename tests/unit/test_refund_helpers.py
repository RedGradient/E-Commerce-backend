from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.domain.order_state_machine import apply_refund
from app.models.models import Order, OrderItem, OrderStatus
from app.services.checkout import OrderNotFound
from app.services.refund import (
    OrderAlreadyRefunded,
    OrderNotRefundable,
    build_refund_payload,
    verify_order_can_be_refunded,
)


def test_verify_order_can_be_refunded_raises_when_missing() -> None:
    with pytest.raises(OrderNotFound):
        verify_order_can_be_refunded(None)


def test_verify_order_can_be_refunded_raises_when_already_refunded() -> None:
    order = Order(id=42, status=OrderStatus.Refunded)
    with pytest.raises(OrderAlreadyRefunded):
        verify_order_can_be_refunded(order)


def test_verify_order_can_be_refunded_raises_when_not_paid() -> None:
    order = Order(id=42, status=OrderStatus.Created)
    with pytest.raises(OrderNotRefundable):
        verify_order_can_be_refunded(order)


def test_verify_order_can_be_refunded_raises_without_payment_intent() -> None:
    order = Order(id=42, status=OrderStatus.Paid, payment_intent_id=None)
    with pytest.raises(OrderNotRefundable):
        verify_order_can_be_refunded(order)


def test_verify_order_can_be_refunded_ok_for_paid_with_pi() -> None:
    order = Order(
        id=42,
        status=OrderStatus.Paid,
        payment_intent_id="pi_abc",
    )
    assert verify_order_can_be_refunded(order) is order


def test_apply_order_refunded_sets_fields() -> None:
    order = Order(id=42, status=OrderStatus.Paid, payment_intent_id="pi_abc")
    at = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)

    apply_refund(order, refunded_at=at)

    assert order.status == OrderStatus.Refunded
    assert order.refunded_at == at


def test_build_refund_payload() -> None:
    order = Order(
        id=42,
        status=OrderStatus.Refunded,
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
    at = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)

    assert build_refund_payload(order, refunded_at=at) == {
        "order_id": 42,
        "payment_intent_id": "pi_abc",
        "status": "Refunded",
        "amount": "19.99",
        "currency": "usd",
        "refunded_at": at.isoformat(),
    }
