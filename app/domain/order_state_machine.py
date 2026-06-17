from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from app.models import Order, OrderStatus


class OrderEvent(Enum):
    START_PAYMENT = "start_payment"
    PAYMENT_SUCCEEDED = "payment_succeeded"
    CANCEL = "cancel"
    REFUND = "refund"


class TransitionOutcome(Enum):
    APPLIED = "applied"
    NOOP = "noop"
    REJECTED = "rejected"


class InvalidOrderTransition(Exception):
    def __init__(
        self,
        *,
        current: OrderStatus,
        event: OrderEvent,
    ) -> None:
        self.current = current
        self.event = event
        super().__init__(
            f"cannot apply {event.value} while order is {current.value}",
        )


@dataclass(frozen=True, slots=True)
class TransitionResult:
    outcome: TransitionOutcome
    from_status: OrderStatus
    to_status: OrderStatus


_TRANSITIONS: dict[tuple[OrderStatus, OrderEvent], OrderStatus] = {
    (OrderStatus.Created, OrderEvent.START_PAYMENT): OrderStatus.Processing,
    (OrderStatus.Processing, OrderEvent.PAYMENT_SUCCEEDED): OrderStatus.Paid,
    (OrderStatus.Created, OrderEvent.CANCEL): OrderStatus.Cancelled,
    (OrderStatus.Paid, OrderEvent.REFUND): OrderStatus.Refunded,
}

# These events are safe to repeat when the order is already in the target status.
# Example: Stripe may deliver payment_succeeded twice; if the order is already Paid,
# we treat the second event as NOOP instead of a rejected transition.
_IDEMPOTENT_EVENTS: dict[OrderEvent, OrderStatus] = {
    OrderEvent.START_PAYMENT: OrderStatus.Processing,
    OrderEvent.PAYMENT_SUCCEEDED: OrderStatus.Paid,
    OrderEvent.CANCEL: OrderStatus.Cancelled,
    OrderEvent.REFUND: OrderStatus.Refunded,
}


def attempt_transition(order: Order, event: OrderEvent) -> TransitionResult:
    current = order.status
    idempotent_target = _IDEMPOTENT_EVENTS.get(event)
    if idempotent_target is not None and current == idempotent_target:
        return TransitionResult(
            outcome=TransitionOutcome.NOOP,
            from_status=current,
            to_status=current,
        )

    target = _TRANSITIONS.get((current, event))
    if target is None:
        return TransitionResult(
            outcome=TransitionOutcome.REJECTED,
            from_status=current,
            to_status=current,
        )

    if target == current:
        return TransitionResult(
            outcome=TransitionOutcome.NOOP,
            from_status=current,
            to_status=current,
        )

    order.status = target
    return TransitionResult(
        outcome=TransitionOutcome.APPLIED,
        from_status=current,
        to_status=target,
    )


def require_transition(order: Order, event: OrderEvent) -> TransitionResult:
    result = attempt_transition(order, event)
    if result.outcome is TransitionOutcome.REJECTED:
        raise InvalidOrderTransition(current=result.from_status, event=event)
    return result


def can_apply_event(status: OrderStatus, event: OrderEvent) -> bool:
    if status == _IDEMPOTENT_EVENTS.get(event):
        return True
    return (status, event) in _TRANSITIONS


def is_checkout_allowed(status: OrderStatus) -> bool:
    return can_apply_event(status, OrderEvent.START_PAYMENT)


def is_cancellation_allowed(status: OrderStatus) -> bool:
    return can_apply_event(status, OrderEvent.CANCEL)


def is_refund_allowed(status: OrderStatus) -> bool:
    return can_apply_event(status, OrderEvent.REFUND)


def apply_start_payment(order: Order, *, payment_intent_id: str) -> TransitionResult:
    result = require_transition(order, OrderEvent.START_PAYMENT)
    order.payment_intent_id = payment_intent_id
    return result


def apply_payment_succeeded(
    order: Order,
    *,
    payment_intent_id: str,
    paid_at: datetime,
) -> TransitionResult:
    result = attempt_transition(order, OrderEvent.PAYMENT_SUCCEEDED)
    if result.outcome is TransitionOutcome.REJECTED:
        return result
    if result.outcome is TransitionOutcome.APPLIED:
        order.payment_intent_id = payment_intent_id
        order.paid_at = paid_at
    return result


def apply_cancellation(
    order: Order,
    *,
    reason: str | None,
    cancelled_at: datetime | None = None,
) -> TransitionResult:
    result = require_transition(order, OrderEvent.CANCEL)
    if result.outcome is TransitionOutcome.APPLIED:
        order.cancel_reason = reason
        order.cancelled_at = cancelled_at or datetime.now(UTC)
    return result


def apply_refund(order: Order, *, refunded_at: datetime) -> TransitionResult:
    result = attempt_transition(order, OrderEvent.REFUND)
    if result.outcome is TransitionOutcome.APPLIED:
        order.refunded_at = refunded_at
    return result
