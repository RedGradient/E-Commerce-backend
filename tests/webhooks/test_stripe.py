from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.events import ORDER_REFUNDED
from app.models.models import Order, OrderStatus
from app.models.outbox import Outbox

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def test_stripe_webhook_success(
    order_factory: Callable[..., Awaitable[Order]],
    db_session: AsyncSession,
    webhook_client: AsyncClient,
) -> None:
    # Prepare Event mock
    fake_event = MagicMock()
    fake_event.type = "payment_intent.succeeded"
    pi = MagicMock()
    pi.id = "payment-intent-id"
    fake_event.data.object = pi
    fake_event.created = 1779279836

    order = await order_factory(
        status=OrderStatus.Processing, payment_intent_id="payment-intent-id"
    )

    # 1. Check if order is paid
    with patch("app.routers.webhooks.Webhook.construct_event", return_value=fake_event):
        response = await webhook_client.post(
            "/webhooks/stripe",
            content=b"{}",
            headers={"Stripe-Signature": "t=1,v1=test"},
        )

    # 2. Check response status
    assert response.status_code == 200
    assert response.json() == {"result": "OK"}

    await db_session.refresh(order)

    # 3. Check order is paid
    assert order.status == OrderStatus.Paid
    assert order.payment_intent_id == "payment-intent-id"
    assert order.paid_at == datetime.fromtimestamp(fake_event.created, tz=UTC)

    # 4. Check if outbox message is created
    outbox_messages = (await db_session.execute(select(Outbox))).scalars().all()
    assert len(outbox_messages) == 1
    assert outbox_messages[0].order_id == order.id


async def test_stripe_webhook_refund_created(
    order_factory: Callable[..., Awaitable[Order]],
    db_session: AsyncSession,
    webhook_client: AsyncClient,
) -> None:
    fake_event = MagicMock()
    fake_event.type = "refund.created"
    fake_event.created = 1779279900
    refund = MagicMock()
    refund.payment_intent = "payment-intent-id"
    fake_event.data.object = refund

    order = await order_factory(
        status=OrderStatus.Paid,
        payment_intent_id="payment-intent-id",
    )

    with patch("app.routers.webhooks.Webhook.construct_event", return_value=fake_event):
        response = await webhook_client.post(
            "/webhooks/stripe",
            content=b"{}",
            headers={"Stripe-Signature": "t=1,v1=test"},
        )

    assert response.status_code == 200
    assert response.json() == {"result": "OK"}

    await db_session.refresh(order)
    assert order.status == OrderStatus.Refunded
    assert order.refunded_at == datetime.fromtimestamp(fake_event.created, tz=UTC)

    outbox_messages = (await db_session.execute(select(Outbox))).scalars().all()
    assert len(outbox_messages) == 1
    assert outbox_messages[0].event_type == ORDER_REFUNDED
    assert outbox_messages[0].payload["refunded_at"] == order.refunded_at.isoformat()
