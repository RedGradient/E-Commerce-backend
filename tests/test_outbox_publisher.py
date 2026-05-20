from datetime import UTC
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.messaging import ORDER_CANCELLED_ROUTING_KEY, ORDER_PAID_ROUTING_KEY
from app.workers import outbox_publisher as publisher


@pytest.mark.asyncio
async def test_publish_by_event_paid_calls_messaging() -> None:
    with patch.object(
        publisher, "publish_order_paid", new_callable=AsyncMock
    ) as mock_paid:
        ok = await publisher.publish_by_event(ORDER_PAID_ROUTING_KEY, {"order_id": 1})
    assert ok is True
    mock_paid.assert_awaited_once_with({"order_id": 1})


@pytest.mark.asyncio
async def test_publish_by_event_cancelled_calls_messaging() -> None:
    with patch.object(
        publisher, "publish_order_cancelled", new_callable=AsyncMock
    ) as mock_cancelled:
        ok = await publisher.publish_by_event(
            ORDER_CANCELLED_ROUTING_KEY, {"order_id": 2}
        )
    assert ok is True
    mock_cancelled.assert_awaited_once_with({"order_id": 2})


@pytest.mark.asyncio
async def test_publish_by_event_unknown_returns_false() -> None:
    with patch.object(
        publisher, "publish_order_paid", new_callable=AsyncMock
    ) as mock_paid:  # noqa: E501
        with patch.object(
            publisher, "publish_order_cancelled", new_callable=AsyncMock
        ) as mock_cancelled:
            ok = await publisher.publish_by_event("order.unknown", {})
    assert ok is False
    mock_paid.assert_not_awaited()
    mock_cancelled.assert_not_awaited()


def test_mark_as_failed_sets_fields() -> None:
    msg = SimpleNamespace(last_error=None, failed_at=None)
    publisher.mark_as_failed(msg, "boom")
    assert msg.last_error == "boom"
    assert msg.failed_at is not None
    assert msg.failed_at.tzinfo is UTC
