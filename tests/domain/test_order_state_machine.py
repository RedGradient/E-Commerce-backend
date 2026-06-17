from datetime import UTC, datetime

import pytest

from app.domain.order_state_machine import (
    InvalidOrderTransition,
    OrderEvent,
    TransitionOutcome,
    apply_cancellation,
    apply_payment_succeeded,
    apply_refund,
    apply_start_payment,
    attempt_transition,
    can_apply_event,
    is_cancellation_allowed,
    is_checkout_allowed,
    is_refund_allowed,
    require_transition,
)
from app.models.models import Order, OrderStatus


@pytest.mark.parametrize(
    ("status", "event", "expected"),
    [
        (OrderStatus.Created, OrderEvent.START_PAYMENT, OrderStatus.Processing),
        (OrderStatus.Processing, OrderEvent.PAYMENT_SUCCEEDED, OrderStatus.Paid),
        (OrderStatus.Created, OrderEvent.CANCEL, OrderStatus.Cancelled),
        (OrderStatus.Paid, OrderEvent.REFUND, OrderStatus.Refunded),
    ],
)
def test_allowed_transitions(
    status: OrderStatus,
    event: OrderEvent,
    expected: OrderStatus,
) -> None:
    order = Order(status=status)
    result = attempt_transition(order, event)

    assert result.outcome is TransitionOutcome.APPLIED
    assert result.from_status is status
    assert result.to_status is expected
    assert order.status is expected


@pytest.mark.parametrize(
    ("status", "event"),
    [
        (OrderStatus.Created, OrderEvent.PAYMENT_SUCCEEDED),
        (OrderStatus.Created, OrderEvent.REFUND),
        (OrderStatus.Processing, OrderEvent.CANCEL),
        (OrderStatus.Processing, OrderEvent.REFUND),
        (OrderStatus.Paid, OrderEvent.CANCEL),
        (OrderStatus.Paid, OrderEvent.START_PAYMENT),
        (OrderStatus.Cancelled, OrderEvent.REFUND),
        (OrderStatus.Refunded, OrderEvent.PAYMENT_SUCCEEDED),
    ],
)
def test_rejected_transitions(status: OrderStatus, event: OrderEvent) -> None:
    order = Order(status=status)
    result = attempt_transition(order, event)

    assert result.outcome is TransitionOutcome.REJECTED
    assert order.status is status


@pytest.mark.parametrize(
    ("status", "event"),
    [
        (OrderStatus.Paid, OrderEvent.PAYMENT_SUCCEEDED),
        (OrderStatus.Refunded, OrderEvent.REFUND),
        (OrderStatus.Cancelled, OrderEvent.CANCEL),
        (OrderStatus.Processing, OrderEvent.START_PAYMENT),
    ],
)
def test_idempotent_transitions(status: OrderStatus, event: OrderEvent) -> None:
    order = Order(status=status)
    result = attempt_transition(order, event)

    assert result.outcome is TransitionOutcome.NOOP
    assert order.status is status


def test_require_transition_raises_on_invalid() -> None:
    order = Order(status=OrderStatus.Created)

    with pytest.raises(InvalidOrderTransition):
        require_transition(order, OrderEvent.REFUND)


def test_is_checkout_allowed() -> None:
    assert is_checkout_allowed(OrderStatus.Created) is True
    assert is_checkout_allowed(OrderStatus.Processing) is True
    assert is_checkout_allowed(OrderStatus.Paid) is False


def test_is_cancellation_allowed() -> None:
    assert is_cancellation_allowed(OrderStatus.Created) is True
    assert is_cancellation_allowed(OrderStatus.Processing) is False
    assert is_cancellation_allowed(OrderStatus.Cancelled) is True


def test_is_refund_allowed() -> None:
    assert is_refund_allowed(OrderStatus.Paid) is True
    assert is_refund_allowed(OrderStatus.Refunded) is True
    assert is_refund_allowed(OrderStatus.Created) is False


def test_apply_start_payment_sets_payment_intent_id() -> None:
    order = Order(status=OrderStatus.Created)
    apply_start_payment(order, payment_intent_id="pi_123")

    assert order.status is OrderStatus.Processing
    assert order.payment_intent_id == "pi_123"


def test_apply_payment_succeeded_sets_paid_fields() -> None:
    order = Order(status=OrderStatus.Processing)
    paid_at = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)

    result = apply_payment_succeeded(
        order,
        payment_intent_id="pi_123",
        paid_at=paid_at,
    )

    assert result.outcome is TransitionOutcome.APPLIED
    assert order.status is OrderStatus.Paid
    assert order.payment_intent_id == "pi_123"
    assert order.paid_at == paid_at


def test_apply_cancellation_sets_fields() -> None:
    order = Order(status=OrderStatus.Created)
    at = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)

    apply_cancellation(order, reason="changed mind", cancelled_at=at)

    assert order.status is OrderStatus.Cancelled
    assert order.cancel_reason == "changed mind"
    assert order.cancelled_at == at


def test_apply_refund_sets_refunded_at() -> None:
    order = Order(status=OrderStatus.Paid)
    at = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)

    result = apply_refund(order, refunded_at=at)

    assert result.outcome is TransitionOutcome.APPLIED
    assert order.status is OrderStatus.Refunded
    assert order.refunded_at == at


def test_can_apply_event() -> None:
    assert can_apply_event(OrderStatus.Paid, OrderEvent.REFUND) is True
    assert can_apply_event(OrderStatus.Created, OrderEvent.REFUND) is False
