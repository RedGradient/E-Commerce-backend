from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.models import OrderStatus
from app.models.outbox import Outbox
from app.services.cancellation import (
    CancellationService,
    OrderAlreadyCancelled,
    OrderNotCancellable,
    apply_cancellation,
    build_cancel_payload,
    verify_order_can_be_cancelled,
)
from app.services.checkout import OrderNotFound


class _FakeOrder:
    def __init__(
        self,
        *,
        order_id: int = 7,
        status: OrderStatus = OrderStatus.Created,
    ) -> None:
        self.id = order_id
        self.status = status
        self.cancelled_at: datetime | None = None
        self.cancel_reason: str | None = None


def test_verify_order_can_be_cancelled_raises_when_missing() -> None:
    with pytest.raises(OrderNotFound):
        verify_order_can_be_cancelled(None)  # type: ignore[arg-type]


def test_verify_order_can_be_cancelled_raises_when_already_cancelled() -> None:
    order = _FakeOrder(status=OrderStatus.Cancelled)
    with pytest.raises(OrderAlreadyCancelled):
        verify_order_can_be_cancelled(order)  # type: ignore[arg-type]


def test_verify_order_can_be_cancelled_raises_when_paid() -> None:
    order = _FakeOrder(status=OrderStatus.Paid)
    with pytest.raises(OrderNotCancellable):
        verify_order_can_be_cancelled(order)  # type: ignore[arg-type]


def test_verify_order_can_be_cancelled_ok_for_created() -> None:
    order = _FakeOrder(status=OrderStatus.Created)
    verify_order_can_be_cancelled(order)  # type: ignore[arg-type] — не бросает


def test_apply_cancellation_sets_fields() -> None:
    order = _FakeOrder()
    apply_cancellation(order, "customer changed mind")  # type: ignore[arg-type]

    assert order.status == OrderStatus.Cancelled
    assert order.cancel_reason == "customer changed mind"
    assert order.cancelled_at is not None
    assert order.cancelled_at.tzinfo is UTC


def test_build_cancel_payload() -> None:
    order = _FakeOrder()
    at = datetime(2026, 5, 18, 12, 0, 0, tzinfo=UTC)
    order.status = OrderStatus.Cancelled
    order.cancel_reason = "x"

    payload = build_cancel_payload(order, cancelled_at=at)  # type: ignore[arg-type]

    assert payload == {
        "order_id": 7,
        "status": "Cancelled",
        "cancelled_at": at.isoformat(),
        "cancel_reason": "x",
    }


@pytest.mark.asyncio
async def test_cancel_happy_path_one_commit_and_outbox() -> None:
    fake_order = _FakeOrder()
    session = MagicMock()
    session.get = AsyncMock(return_value=fake_order)
    session.add = MagicMock()
    session.commit = AsyncMock()

    payload = await CancellationService().cancel(
        fake_order.id,
        session,
        reason="test reason",
    )

    assert fake_order.status == OrderStatus.Cancelled
    assert fake_order.cancel_reason == "test reason"
    assert payload["order_id"] == fake_order.id
    assert payload["cancel_reason"] == "test reason"
    assert "cancelled_at" in payload

    added = [call.args[0] for call in session.add.call_args_list]
    outbox_rows = [obj for obj in added if isinstance(obj, Outbox)]
    assert len(outbox_rows) == 1
    assert outbox_rows[0].event_type == "order.cancelled"
    assert outbox_rows[0].order_id == fake_order.id
    assert outbox_rows[0].payload == payload

    session.get.assert_awaited_once()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancel_does_not_commit_when_order_not_found() -> None:
    session = MagicMock()
    session.get = AsyncMock(return_value=None)
    session.commit = AsyncMock()

    with pytest.raises(OrderNotFound):
        await CancellationService().cancel(order_id=99, session=session)

    session.commit.assert_not_called()
