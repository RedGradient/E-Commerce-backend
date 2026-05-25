import asyncio
import json
import logging
from json import JSONDecodeError

from aio_pika.abc import AbstractIncomingMessage

from app.messaging import (
    ORDER_CANCELLED_ROUTING_KEY,
    ORDER_PAID_ROUTING_KEY,
    ORDER_REFUNDED_ROUTING_KEY,
    _get_order_events_exchange,
    get_or_create_rabbit_connection,
)

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger(__file__)

ORDER_EVENTS_QUEUE = "order.events.notifications"


async def message_handler(message: AbstractIncomingMessage) -> None:
    async with message.process():
        logger.info("Received routing key: %s", message.routing_key)

        try:
            msg = json.loads(message.body)
        except JSONDecodeError:
            logger.error("Can not decode the message. Abort handling message")
            return

        if message.routing_key == ORDER_PAID_ROUTING_KEY:
            handle_order_paid(msg)
        elif message.routing_key == ORDER_CANCELLED_ROUTING_KEY:
            handle_order_cancelled(msg)
        elif message.routing_key == ORDER_REFUNDED_ROUTING_KEY:
            handle_order_refunded(msg)
        else:
            logger.warning(
                f"Message with unhandled routing_key '{message.routing_key}': {msg}"
            )


def handle_order_paid(msg: dict) -> None:
    logger.info(f"Handling order.paid message: {msg}")


def handle_order_cancelled(msg: dict) -> None:
    logger.info(f"Handling order.cancelled message: {msg}")


def handle_order_refunded(msg: dict) -> None:
    logger.info(f"Handling order.refunded message: {msg}")


async def main() -> None:
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
