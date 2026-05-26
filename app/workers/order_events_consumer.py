import asyncio
import json
import logging
from json import JSONDecodeError

from aio_pika.abc import AbstractIncomingMessage

from app.log_config import configure_logging
from app.logging_context import log_context, log_extra
from app.messaging import (
    ORDER_CANCELLED_ROUTING_KEY,
    ORDER_PAID_ROUTING_KEY,
    ORDER_REFUNDED_ROUTING_KEY,
    _get_order_events_exchange,
    get_or_create_rabbit_connection,
)

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

        with log_context(
            routing_key=message.routing_key,
            order_id=payload.get("order_id"),
        ):
            logger.info(
                "RabbitMQ message received",
                extra=log_extra(event="consumer.message.received"),
            )

            if message.routing_key == ORDER_PAID_ROUTING_KEY:
                handle_order_paid(payload)
            elif message.routing_key == ORDER_CANCELLED_ROUTING_KEY:
                handle_order_cancelled(payload)
            elif message.routing_key == ORDER_REFUNDED_ROUTING_KEY:
                handle_order_refunded(payload)
            else:
                logger.warning(
                    "Unhandled RabbitMQ routing key",
                    extra=log_extra(event="consumer.message.unhandled"),
                )


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
        await queue.bind(exchange, routing_key=ORDER_PAID_ROUTING_KEY)
        await queue.bind(exchange, routing_key=ORDER_CANCELLED_ROUTING_KEY)
        await queue.bind(exchange, routing_key=ORDER_REFUNDED_ROUTING_KEY)

        await queue.consume(message_handler)

        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())
