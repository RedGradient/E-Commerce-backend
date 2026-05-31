import asyncio
import logging
from datetime import timedelta

import prometheus_client
from sqlalchemy import func, select

from app.log_config import configure_logging
from app.logging_context import log_context, log_extra
from app.models.models import Order, OrderStatus
from app.observability.metrics import record_order_cancellation
from app.services.cancellation import (
    CancellationService,
    OrderAlreadyCancelled,
    OrderNotCancellable,
)
from app.services.checkout import OrderNotFound
from app.session import get_sessionmaker

configure_logging()
logger = logging.getLogger(__name__)

CANCELLATION_EVENT_TYPE = "cancellator"
STALE_ORDER_AFTER = timedelta(seconds=10)
BATCH_SIZE = 50
IDLE_SLEEP_SECONDS = 3


async def run_batch(
    *,
    stale_after: timedelta = STALE_ORDER_AFTER,
    batch_size: int = BATCH_SIZE,
) -> int:
    service = CancellationService()
    candidate_stmt = (
        select(Order.id)
        .where(Order.status == OrderStatus.Created)
        .where(Order.created_at < func.now() - stale_after)
        .limit(batch_size)
    )

    async with get_sessionmaker()() as session:
        order_ids = (await session.execute(candidate_stmt)).scalars().all()

    if not order_ids:
        return 0

    logger.info(
        "Found orders to cancel",
        extra=log_extra(
            event="worker.cancellator.batch_found",
            batch_size=len(order_ids),
        ),
    )

    cancelled_count = 0
    for order_id in order_ids:
        with log_context(order_id=order_id):
            async with get_sessionmaker()() as session:
                try:
                    await service.cancel(
                        order_id=order_id,
                        session=session,
                        reason="timeout",
                    )
                    cancelled_count += 1
                    record_order_cancellation(
                        event_type=CANCELLATION_EVENT_TYPE,
                        outcome="cancelled",
                    )
                except OrderAlreadyCancelled:
                    logger.info(
                        "Order already cancelled, skipping",
                        extra=log_extra(event="worker.cancellator.skipped"),
                    )
                    record_order_cancellation(
                        event_type=CANCELLATION_EVENT_TYPE,
                        outcome="already_cancelled",
                    )
                except OrderNotCancellable:
                    logger.warning(
                        "Order not cancellable, skipping",
                        extra=log_extra(event="worker.cancellator.not_cancellable"),
                    )
                    record_order_cancellation(
                        event_type=CANCELLATION_EVENT_TYPE,
                        outcome="not_cancellable",
                    )
                except OrderNotFound:
                    logger.warning(
                        "Order not found, skipping",
                        extra=log_extra(event="worker.cancellator.not_found"),
                    )
                    record_order_cancellation(
                        event_type=CANCELLATION_EVENT_TYPE,
                        outcome="not_found",
                    )
                except Exception:
                    logger.exception(
                        "Failed to cancel order",
                        extra=log_extra(event="worker.cancellator.failed"),
                    )
                    record_order_cancellation(
                        event_type=CANCELLATION_EVENT_TYPE,
                        outcome="failed",
                    )

    logger.info(
        "Cancellation batch finished",
        extra=log_extra(
            event="worker.cancellator.batch_done",
            batch_size=len(order_ids),
            cancelled_count=cancelled_count,
        ),
    )

    return cancelled_count


async def main() -> None:
    logger.info(
        "Order cancelling worker started",
        extra=log_extra(event="worker.cancellator.started"),
    )

    prometheus_client.start_http_server(9092)

    while True:
        cancelled_count = await run_batch()
        if cancelled_count == 0:
            await asyncio.sleep(IDLE_SLEEP_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
