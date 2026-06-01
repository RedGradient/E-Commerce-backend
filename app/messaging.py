import json

import aio_pika

from app.config import settings
from app.events import ORDER_CANCELLED, ORDER_PAID, ORDER_REFUNDED

_rabbit_client: aio_pika.abc.AbstractRobustConnection | None = None


async def get_or_create_rabbit_connection() -> aio_pika.abc.AbstractRobustConnection:
    global _rabbit_client
    if _rabbit_client is None:
        _rabbit_client = await aio_pika.connect_robust(settings.rabbitmq_dsn)
    return _rabbit_client


async def dispose_rabbit():
    global _rabbit_client
    if _rabbit_client is not None:
        await _rabbit_client.close()
        _rabbit_client = None


ORDER_EVENTS_EXCHANGE = "order.events"


async def _get_order_events_exchange(
    channel: aio_pika.abc.AbstractChannel,
) -> aio_pika.abc.AbstractExchange:
    return await channel.declare_exchange(
        name=ORDER_EVENTS_EXCHANGE,
        type=aio_pika.ExchangeType.TOPIC,
        durable=True,
    )


async def publish_order_paid(payload: dict) -> None:
    connection = await get_or_create_rabbit_connection()

    async with connection.channel() as channel:
        exchange = await _get_order_events_exchange(channel)

        message = aio_pika.Message(
            body=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )

        await exchange.publish(
            message=message,
            routing_key=ORDER_PAID,
        )


async def publish_order_cancelled(payload: dict) -> None:
    connection = await get_or_create_rabbit_connection()

    async with connection.channel() as channel:
        exchange = await _get_order_events_exchange(channel)

        message = aio_pika.Message(
            body=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )

        await exchange.publish(
            message=message,
            routing_key=ORDER_CANCELLED,
        )


async def publish_order_refunded(payload: dict) -> None:
    connection = await get_or_create_rabbit_connection()

    async with connection.channel() as channel:
        exchange = await _get_order_events_exchange(channel)

        message = aio_pika.Message(
            body=json.dumps(payload).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )

        await exchange.publish(
            message=message,
            routing_key=ORDER_REFUNDED,
        )
