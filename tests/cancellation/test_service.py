from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import ORDER_CANCELLED
from app.models import Order, OrderStatus
from app.models.outbox import Outbox
from app.services.cancellation import CancellationService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_cancellation_ok(
    order_factory: Callable[..., Awaitable[Order]],
    db_session: AsyncSession,
):
    order = await order_factory(status=OrderStatus.Created)

    service = CancellationService()
    await service.cancel(order.id, db_session, reason="this is the reason")

    await db_session.refresh(order)
    messages = (
        (
            await db_session.execute(
                select(Outbox)
                .where(Outbox.order_id == order.id)
                .where(Outbox.event_type == ORDER_CANCELLED)
            )
        )
        .scalars()
        .all()
    )

    assert order.status == OrderStatus.Cancelled
    assert order.cancel_reason == "this is the reason"
    assert len(messages) == 1
    assert messages[0].event_type == ORDER_CANCELLED
    assert messages[0].payload["cancel_reason"] == "this is the reason"
