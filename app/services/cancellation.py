import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.order_state_machine import apply_cancellation, is_cancellation_allowed
from app.logging_context import log_context, log_extra
from app.models.models import Order, OrderStatus
from app.models.outbox import Outbox
from app.services.checkout import OrderNotFound

logger = logging.getLogger(__name__)


def _is_outbox_dedup_hit(err: IntegrityError) -> bool:
    return "uq_outbox_dedup_key" in str(err.orig)


def outbox_cancel_message(order: Order, *, dedup_key: str, payload: dict) -> Outbox:
    return Outbox(
        event_type="order.cancelled",
        dedup_key=dedup_key,
        order_id=order.id,  # type: ignore[arg-type]
        payload=payload,
    )


class OrderAlreadyCancelled(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class OrderNotCancellable(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class CancellationService:
    async def cancel(
        self,
        order_id: int,
        session: AsyncSession,
        reason: str | None = None,
    ) -> dict:
        with log_context(order_id=order_id, cancel_reason=reason):
            order = await session.get(Order, order_id)
            verify_order_can_be_cancelled(order)

            cancelled_at = datetime.now(UTC)
            apply_cancellation(order, reason=reason, cancelled_at=cancelled_at)

            payload = build_cancel_payload(order, cancelled_at=cancelled_at)
            dedup_key = f"order.cancelled:{order.id}"
            try:
                session.add(
                    outbox_cancel_message(order, dedup_key=dedup_key, payload=payload)
                )
                await session.commit()
            except IntegrityError as err:
                await session.rollback()
                if _is_outbox_dedup_hit(err):
                    logger.info(
                        "Outbox dedup hit for cancelled event",
                        extra=log_extra(
                            event="outbox.dedup_hit",
                            dedup_key=dedup_key,
                            dedup_scope="order.cancelled",
                        ),
                    )
                    return payload
                logger.exception(
                    "Failed to persist outbox message for cancelled event",
                    extra=log_extra(
                        event="outbox.persist_failed",
                        dedup_key=dedup_key,
                        dedup_scope="order.cancelled",
                        db_error=str(err.orig),
                    ),
                )
                raise

            logger.info(
                "Order cancelled",
                extra=log_extra(event="order.cancelled"),
            )
            return payload


def verify_order_can_be_cancelled(order: Order) -> None:
    if order is None:
        raise OrderNotFound()

    if order.status == OrderStatus.Cancelled:
        raise OrderAlreadyCancelled()

    if not is_cancellation_allowed(order.status):
        raise OrderNotCancellable()


def build_cancel_payload(order: Order, cancelled_at: datetime) -> dict:
    return {
        "order_id": order.id,
        "status": order.status.value,
        "cancelled_at": cancelled_at.isoformat(),
        "cancel_reason": order.cancel_reason,
    }
