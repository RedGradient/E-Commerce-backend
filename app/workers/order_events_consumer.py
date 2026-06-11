import asyncio
import json
import logging
from datetime import UTC, datetime
from json import JSONDecodeError

from aio_pika.abc import AbstractIncomingMessage

from app.events import ORDER_CANCELLED, ORDER_PAID, ORDER_REFUNDED
from app.log_config import configure_logging
from app.logging_context import (
    clear_log_context,
    log_extra,
    update_log_context,
)
from app.messaging import (
    _get_order_events_exchange,
    get_or_create_rabbit_connection,
)
from app.models.processed_events import ProcessedEvent
from app.session import get_sessionmaker

configure_logging()
logger = logging.getLogger(__name__)

ORDER_EVENTS_QUEUE = "order.events.notifications"


async def message_handler(message: AbstractIncomingMessage) -> None:
    async with message.process():
        try:
            payload = json.loads(message.body)
        except JSONDecodeError:
            logger.error(
                "Failed to decode RabbitMQ message",
                extra=log_extra(
                    event="consumer.message.decode_failed",
                    routing_key=message.routing_key,
                ),
            )
            return

        required_keys = {"dedup_key", "event_type", "order_id"}
        missing_keys = required_keys - payload.keys()
        if missing_keys:
            logger.error(
                "The payload is missing required keys",
                extra=log_extra(
                    event="consumer.message.missing_keys",
                    routing_key=message.routing_key,
                    missing_keys=sorted(missing_keys),
                ),
            )
            return

        update_log_context(
            routing_key=message.routing_key,
            order_id=payload.get("order_id"),
        )

        async with get_sessionmaker()() as session:
            dedup_key = payload["dedup_key"]
            if await session.get(ProcessedEvent, dedup_key):
                logger.info(
                    "Skip RabbitMQ duplicate message",
                    extra=log_extra(
                        event="consumer.message.duplicate",
                        dedup_key=dedup_key,
                    ),
                )
                return

            session.add(
                ProcessedEvent(
                    dedup_key=payload["dedup_key"],
                    event_type=payload["event_type"],
                    order_id=payload["order_id"],
                    processed_at=datetime.now(UTC),
                )
            )

            await session.commit()

        logger.info(
            "RabbitMQ message received",
            extra=log_extra(event="consumer.message.received"),
        )

        if message.routing_key == ORDER_PAID:
            handle_order_paid(payload)
        elif message.routing_key == ORDER_CANCELLED:
            handle_order_cancelled(payload)
        elif message.routing_key == ORDER_REFUNDED:
            handle_order_refunded(payload)
        else:
            logger.warning(
                "Unhandled RabbitMQ routing key",
                extra=log_extra(event="consumer.message.unhandled"),
            )

        clear_log_context()


def handle_order_paid(msg: dict) -> None:
    logger.info(
        "Processed order.paid event",
        extra=log_extra(event="consumer.order.paid"),
    )


def handle_order_cancelled(msg: dict) -> None:
    logger.info(
        "Processed order.cancelled event",
        extra=log_extra(event="consumer.order.cancelled"),
    )


def handle_order_refunded(msg: dict) -> None:
    logger.info(
        "Processed order.refunded event",
        extra=log_extra(event="consumer.order.refunded"),
    )


async def main() -> None:
    logger.info(
        "Order events consumer started",
        extra=log_extra(event="worker.consumer.started"),
    )
    connection = await get_or_create_rabbit_connection()

    async with connection.channel() as channel:
        exchange = await _get_order_events_exchange(channel)
        queue = await channel.declare_queue(name=ORDER_EVENTS_QUEUE, durable=True)
        await queue.bind(exchange, routing_key=ORDER_PAID)
        await queue.bind(exchange, routing_key=ORDER_CANCELLED)
        await queue.bind(exchange, routing_key=ORDER_REFUNDED)

        await queue.consume(message_handler)

        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
