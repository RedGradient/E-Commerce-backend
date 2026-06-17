from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import ORDER_REFUNDED
from app.models import Order, OrderStatus
from app.models.outbox import Outbox
from app.services.refund import RefundService

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_refund_ok(
    order_factory: Callable[..., Awaitable[Order]],
    db_session: AsyncSession,
    stripe_webhook_asgi: None,
):
    order = await order_factory(
        status=OrderStatus.Paid,
        payment_intent_id="pi_test_123",
    )

    payload = await RefundService().refund(order_id=order.id, session=db_session)

    assert payload["order_id"] == order.id
    assert payload["status"] == OrderStatus.Refunded
    assert payload["stripe_refund_id"].startswith("re_mock_")
    assert payload["message"] == "refund initiated; order status updates via webhook"

    await db_session.refresh(order)
    assert order.status == OrderStatus.Refunded
    assert order.refunded_at is not None

    messages = (
        (
            await db_session.execute(
                select(Outbox)
                .where(Outbox.order_id == order.id)
                .where(Outbox.event_type == ORDER_REFUNDED)
            )
        )
        .scalars()
        .all()
    )

    assert len(messages) == 1
    assert messages[0].event_type == ORDER_REFUNDED
    assert messages[0].payload["status"] == "Refunded"
