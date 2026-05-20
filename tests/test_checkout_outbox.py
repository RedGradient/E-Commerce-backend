from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.integrations.stripe_client import StripeClient, StripePaymentError
from app.models.models import OrderStatus
from app.models.outbox import Outbox
from app.services.checkout import (
    CheckoutService,
    IdempotencyInProgress,
    OrderNotFound,
    OrderNotPayable,
    PaymentFailed,
    apply_order_paid,
    build_checkout_payload,
    outbox_checkout_message,
    read_idempotency,
    validate_order,
)


class _FakeOrder:
    def __init__(
        self,
        *,
        order_id: int = 42,
        status: OrderStatus = OrderStatus.Created,
    ) -> None:
        self.id = order_id
        self.status = status
        self.payment_intent_id: str | None = None
        self.paid_at: datetime | None = None
        self.items: list = []

    @property
    def total_price(self) -> Decimal:
        return Decimal("19.99")


# --- pure helpers ---


def test_validate_order_raises_when_missing() -> None:
    with pytest.raises(OrderNotFound):
        validate_order(None)


def test_validate_order_raises_when_not_payable() -> None:
    with pytest.raises(OrderNotPayable):
        validate_order(_FakeOrder(status=OrderStatus.Paid))  # type: ignore[arg-type]


def test_validate_order_accepts_created_and_processing() -> None:
    order = validate_order(_FakeOrder(status=OrderStatus.Created))  # type: ignore[arg-type]
    assert order.status == OrderStatus.Created
    assert validate_order(_FakeOrder(status=OrderStatus.Processing)).status == (  # type: ignore[arg-type]
        OrderStatus.Processing
    )


def test_apply_order_paid_sets_fields() -> None:
    order = _FakeOrder()
    at = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
    apply_order_paid(order, "pi_123", paid_at=at)  # type: ignore[arg-type]

    assert order.status == OrderStatus.Paid
    assert order.payment_intent_id == "pi_123"
    assert order.paid_at == at


def test_build_checkout_payload() -> None:
    order = _FakeOrder()
    at = datetime(2026, 5, 18, 12, 0, tzinfo=UTC)
    apply_order_paid(order, "pi_abc", paid_at=at)  # type: ignore[arg-type]

    assert build_checkout_payload(order) == {  # type: ignore[arg-type]
        "order_id": 42,
        "payment_intent_id": "pi_abc",
        "status": "Paid",
        "amount": "19.99",
        "currency": "usd",
        "paid_at": at.isoformat(),
    }


def test_outbox_checkout_message() -> None:
    payload = {"order_id": 42}
    msg = outbox_checkout_message(42, payload)
    assert msg.event_type == "order.paid"
    assert msg.order_id == 42
    assert msg.payload == payload


@pytest.mark.asyncio
async def test_read_idempotency_returns_none_when_key_missing() -> None:
    with patch(
        "app.services.checkout.get_idempotency_result",
        new_callable=AsyncMock,
        return_value=None,
    ):
        assert await read_idempotency("key") is None


@pytest.mark.asyncio
async def test_read_idempotency_returns_payload_when_completed() -> None:
    cached = {"order_id": 1}
    with patch(
        "app.services.checkout.get_idempotency_result",
        new_callable=AsyncMock,
        return_value={"status": "completed", "payload": cached},
    ):
        assert await read_idempotency("key") == cached


@pytest.mark.asyncio
async def test_read_idempotency_raises_when_processing() -> None:
    with patch(
        "app.services.checkout.get_idempotency_result",
        new_callable=AsyncMock,
        return_value={"status": "processing"},
    ):
        with pytest.raises(IdempotencyInProgress):
            await read_idempotency("key")


# --- CheckoutService ---


@pytest.mark.asyncio
async def test_checkout_happy_path_paid_outbox_one_commit() -> None:
    fake_order = _FakeOrder()
    session = MagicMock()
    session.get = AsyncMock(return_value=fake_order)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    stripe = MagicMock(spec=StripeClient)
    stripe.create_payment_intent = AsyncMock(
        return_value=MagicMock(id="pi_test_abc", status="succeeded")
    )

    with (
        patch(
            "app.services.checkout.read_idempotency",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.checkout.reserve_idempotency",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.services.checkout.save_idempotency_result",
            new_callable=AsyncMock,
        ) as mock_save_idem,
    ):
        payload = await CheckoutService(stripe).checkout(
            fake_order.id, "idem-key", session
        )

    assert fake_order.status == OrderStatus.Paid
    assert payload["payment_intent_id"] == "pi_test_abc"
    assert payload["paid_at"] is not None

    outbox_rows = [
        c.args[0] for c in session.add.call_args_list if isinstance(c.args[0], Outbox)
    ]  # noqa: E501
    assert len(outbox_rows) == 1
    assert outbox_rows[0].event_type == "order.paid"
    assert outbox_rows[0].order_id == fake_order.id

    session.flush.assert_awaited_once()
    session.commit.assert_awaited_once()
    stripe.create_payment_intent.assert_awaited_once()
    mock_save_idem.assert_awaited_once()


@pytest.mark.asyncio
async def test_checkout_returns_cached_without_loading_order() -> None:
    cached = {"order_id": 1, "status": "Paid"}
    session = MagicMock()
    session.get = AsyncMock()

    with patch(
        "app.services.checkout.read_idempotency",
        new_callable=AsyncMock,
        return_value=cached,
    ):
        result = await CheckoutService(MagicMock(spec=StripeClient)).checkout(
            99, "same-key", session
        )

    assert result == cached
    session.get.assert_not_awaited()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_checkout_after_failed_reserve_returns_cached() -> None:
    cached = {"order_id": 1, "status": "Paid"}
    session = MagicMock()
    session.get = AsyncMock(return_value=_FakeOrder())

    with (
        patch(
            "app.services.checkout.read_idempotency",
            new_callable=AsyncMock,
            side_effect=[None, cached],
        ),
        patch(
            "app.services.checkout.reserve_idempotency",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        result = await CheckoutService(MagicMock(spec=StripeClient)).checkout(
            42, "race-key", session
        )

    assert result == cached
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_checkout_raises_in_progress_when_reserve_fails_and_still_processing() -> None:  # fmt: skip  # noqa: E501
    session = MagicMock()
    session.get = AsyncMock(return_value=_FakeOrder())

    with (
        patch(
            "app.services.checkout.read_idempotency",
            new_callable=AsyncMock,
            side_effect=[None, IdempotencyInProgress()],
        ),
        patch(
            "app.services.checkout.reserve_idempotency",
            new_callable=AsyncMock,
            return_value=False,
        ),
    ):
        with pytest.raises(IdempotencyInProgress):
            await CheckoutService(MagicMock(spec=StripeClient)).checkout(
                42, "busy-key", session
            )


@pytest.mark.asyncio
async def test_checkout_payment_failed_releases_idempotency_key() -> None:
    session = MagicMock()
    session.get = AsyncMock(return_value=_FakeOrder())
    session.flush = AsyncMock()

    stripe = MagicMock(spec=StripeClient)
    stripe.create_payment_intent = AsyncMock(side_effect=StripePaymentError("fail"))

    with (
        patch(
            "app.services.checkout.read_idempotency",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "app.services.checkout.reserve_idempotency",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "app.services.checkout.release_idempotency_key",
            new_callable=AsyncMock,
        ) as mock_release,
    ):
        with pytest.raises(PaymentFailed):
            await CheckoutService(stripe).checkout(42, "idem", session)

    mock_release.assert_awaited_once_with("idem")
    session.commit.assert_not_called()
