from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import pytest

from app.models.models import Order, OrderStatus
from app.workers import order_cancellator


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_cancellator_is_cancelling(
    order_factory: Callable[..., Awaitable[Order]],
):
    stale_created_at = datetime.now(UTC) - timedelta(minutes=1)

    for _ in range(0, 10):
        await order_factory(
            status=OrderStatus.Created,
            created_at=stale_created_at,
        )

    cancelled_count = await order_cancellator.run_batch(
        stale_after=timedelta(seconds=0), batch_size=10
    )

    assert cancelled_count == 10


@pytest.mark.integration
@pytest.mark.asyncio
async def test_order_cancellator_is_not_cancelling(
    order_factory: Callable[..., Awaitable[Order]],
):
    await order_factory(status=OrderStatus.Created)

    cancelled_count = await order_cancellator.run_batch(
        stale_after=timedelta(seconds=5), batch_size=10
    )

    assert cancelled_count == 0
