import json
from contextlib import asynccontextmanager
from unittest.mock import MagicMock

import pytest
from aio_pika.abc import AbstractIncomingMessage
from sqlalchemy import func, select

from app.events import ORDER_PAID
from app.models.processed_events import ProcessedEvent
from app.workers.order_events_consumer import (
    MessageHandlerOutcome,
    MessageHandlerResult,
    message_handler,
)


@asynccontextmanager
async def _noop_process(*args, **kwargs):
    yield


def make_incoming_message(payload: dict, routing_key: str) -> MagicMock:
    message = MagicMock(spec=AbstractIncomingMessage)
    message.body = json.dumps(payload).encode("utf-8")
    message.routing_key = routing_key
    message.process = MagicMock(side_effect=_noop_process)
    return message


def make_invalid_json_message(routing_key: str = ORDER_PAID) -> MagicMock:
    message = MagicMock(spec=AbstractIncomingMessage)
    message.body = b"{not-json"
    message.routing_key = routing_key
    message.process = MagicMock(side_effect=_noop_process)
    return message


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_ok(db_session) -> None:
    payload = {
        "dedup_key": "stripe:evt_mock_123",
        "order_id": 1,
        "event_type": ORDER_PAID,
    }
    message = make_incoming_message(payload, ORDER_PAID)
    result = await message_handler(message=message)

    dedup_key = "stripe:evt_mock_123"
    assert result == MessageHandlerResult(
        outcome=MessageHandlerOutcome.PROCESSED,
        dedup_key=dedup_key,
        order_id=1,
    )

    processed_event = await db_session.get(ProcessedEvent, dedup_key)
    assert processed_event is not None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_duplicate_message(db_session) -> None:
    payload = {
        "dedup_key": "stripe:evt_mock_123",
        "order_id": 1,
        "event_type": ORDER_PAID,
    }
    message = make_incoming_message(payload, ORDER_PAID)

    result1 = await message_handler(message=message)
    result2 = await message_handler(message=message)

    assert result1 == MessageHandlerResult(
        outcome=MessageHandlerOutcome.PROCESSED,
        dedup_key="stripe:evt_mock_123",
        order_id=1,
    )
    assert result2 == MessageHandlerResult(
        outcome=MessageHandlerOutcome.DUPLICATE,
        dedup_key="stripe:evt_mock_123",
        order_id=1,
    )

    count = await db_session.scalar(
        select(func.count())
        .select_from(ProcessedEvent)
        .where(ProcessedEvent.dedup_key == "stripe:evt_mock_123")
    )
    assert count == 1


@pytest.mark.asyncio
async def test_worker_missing_key() -> None:
    payload = {
        "dedup_key": "stripe:evt_mock_123",
        "order_id": 1,
        # "event_type": ORDER_PAID   <--- missed key
    }
    message = make_incoming_message(payload, ORDER_PAID)
    result = await message_handler(message=message)

    assert result == MessageHandlerResult(
        outcome=MessageHandlerOutcome.MISSING_KEYS,
        missing_keys=frozenset({"event_type"}),
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_worker_unhandled_routing_key(db_session) -> None:
    payload = {
        "dedup_key": "stripe:evt_unhandled_123",
        "order_id": 1,
        "event_type": ORDER_PAID,
    }
    message = make_incoming_message(payload, "unknown.routing.key")
    result = await message_handler(message=message)

    assert result == MessageHandlerResult(
        outcome=MessageHandlerOutcome.UNHANDLED_ROUTING_KEY,
        dedup_key="stripe:evt_unhandled_123",
        order_id=1,
    )


@pytest.mark.asyncio
async def test_worker_invalid_json() -> None:
    message = make_invalid_json_message(ORDER_PAID)
    result = await message_handler(message=message)

    assert result == MessageHandlerResult(outcome=MessageHandlerOutcome.INVALID_JSON)
