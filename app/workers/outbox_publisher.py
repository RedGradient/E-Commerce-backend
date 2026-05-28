import asyncio
import logging
import time
from datetime import UTC, datetime

import prometheus_client
from sqlalchemy import select

from app.log_config import configure_logging
from app.logging_context import log_context, log_extra
from app.messaging import (
    ORDER_CANCELLED_ROUTING_KEY,
    ORDER_PAID_ROUTING_KEY,
    ORDER_REFUNDED_ROUTING_KEY,
    publish_order_cancelled,
    publish_order_paid,
    publish_order_refunded,
)
from app.models.models import Order  # noqa: F401
from app.models.outbox import Outbox
from app.observability.metrics import record_outbox_publish
from app.session import get_sessionmaker

configure_logging()
logger = logging.getLogger(__name__)

MAX_ATTEMPTS: int = 5


async def publish_by_event(event_type: str, payload: dict) -> bool:
    if event_type == ORDER_PAID_ROUTING_KEY:
        await publish_order_paid(payload)
    elif event_type == ORDER_CANCELLED_ROUTING_KEY:
        await publish_order_cancelled(payload)
    elif event_type == ORDER_REFUNDED_ROUTING_KEY:
        await publish_order_refunded(payload)
    else:
        return False
    return True


def mark_as_failed(msg: Outbox, error: str) -> None:
    msg.last_error = error
    msg.failed_at = datetime.now(UTC)


async def main() -> None:
    prometheus_client.start_http_server(9091)

    logger.info(
        "Outbox publisher started",
        extra=log_extra(event="worker.outbox.started"),
    )

    while True:
        async with get_sessionmaker()() as session:
            published_any = False

            stmt = (
                select(Outbox)
                .where(Outbox.published_at.is_(None))
                .where(Outbox.failed_at.is_(None))
                .order_by(Outbox.id)
                .limit(50)
                .with_for_update(skip_locked=True)
            )

            async with session.begin():
                messages = (await session.execute(stmt)).scalars().all()

                for msg in messages:
                    start = time.perf_counter()
                    with log_context(
                        outbox_id=msg.id,
                        order_id=msg.order_id,
                        event_type=msg.event_type,
                    ):
                        try:
                            if not await publish_by_event(msg.event_type, msg.payload):
                                error = f"unknown event_type {msg.event_type}"
                                logger.warning(
                                    "Outbox publish skipped",
                                    extra=log_extra(
                                        event="outbox.publish.unknown_event",
                                        error=error,
                                    ),
                                )
                                mark_as_failed(msg, error)
                                record_outbox_publish(
                                    event_type=msg.event_type,
                                    result="skipped",
                                    duration_seconds=time.perf_counter() - start,
                                )
                                continue
                        except Exception:
                            msg.attempts += 1
                            logger.exception(
                                "Outbox publish failed",
                                extra=log_extra(
                                    event="outbox.publish.failed",
                                    attempt=msg.attempts,
                                    max_attempts=MAX_ATTEMPTS,
                                ),
                            )

                            if msg.attempts >= MAX_ATTEMPTS:
                                mark_as_failed(
                                    msg,
                                    f"failed after {MAX_ATTEMPTS} attempts",
                                )
                            record_outbox_publish(
                                event_type=msg.event_type,
                                result="failed",
                                duration_seconds=time.perf_counter() - start,
                            )
                            continue

                        msg.published_at = datetime.now(UTC)
                        logger.info(
                            "Outbox message published",
                            extra=log_extra(event="outbox.publish.success"),
                        )
                        published_any = True
                        record_outbox_publish(
                            event_type=msg.event_type,
                            result="published",
                            duration_seconds=time.perf_counter() - start,
                        )

            if not published_any:
                await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
