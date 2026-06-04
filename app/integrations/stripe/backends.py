import asyncio
import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol
from uuid import uuid4

import stripe

from app.config import settings
from app.integrations.stripe.errors import StripePaymentError
from app.integrations.stripe.mappers import map_payment_intent, map_refund
from app.integrations.stripe.models import StripePaymentIntent, StripeRefund
from app.integrations.stripe.webhook_simulator import StripeWebhookSimulator
from app.logging_context import log_extra

logger = logging.getLogger(__name__)

MOCK_WEBHOOK_DELAY_SECONDS = 0.3


class StripeBackend(Protocol):
    async def create_payment_intent(
        self,
        amount: Decimal,
        idempotency_key: str,
        currency: str,
        metadata: dict[str, str] | None = None,
    ) -> StripePaymentIntent: ...

    async def refund(
        self,
        order_id: int,
        payment_intent_id: str,
    ) -> StripeRefund: ...


class SdkStripeBackend:
    def __init__(self, api_key: str) -> None:
        self._client = stripe.StripeClient(api_key=api_key)

    async def create_payment_intent(
        self,
        amount: Decimal,
        idempotency_key: str,
        currency: str,
        metadata: dict[str, str] | None = None,
    ) -> StripePaymentIntent:
        order_id = metadata.get("order_id") if metadata else None
        amount_cents = int(
            (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

        try:
            payment_intent = await self._client.v1.payment_intents.create_async(
                params={
                    "amount": amount_cents,
                    "currency": currency.lower(),
                    "metadata": metadata or {},
                    "payment_method": "pm_card_visa",
                    "confirm": True,
                    "automatic_payment_methods": {
                        "enabled": True,
                        "allow_redirects": "never",
                    },
                },
                options={"idempotency_key": idempotency_key},
            )
        except stripe.StripeError as err:
            logger.error(
                "Stripe payment_intent request failed",
                extra=log_extra(
                    event="stripe.payment_intent.failed",
                    order_id=order_id,
                    error=str(err),
                ),
            )
            raise StripePaymentError(str(err)) from err

        if payment_intent.status != "succeeded":
            logger.error(
                "Stripe payment_intent unexpected status",
                extra=log_extra(
                    event="stripe.payment_intent.unexpected_status",
                    order_id=order_id,
                    payment_intent_id=payment_intent.id,
                    payment_intent_status=payment_intent.status,
                ),
            )
            raise StripePaymentError("payment intent is not succeeded")

        logger.info(
            "Stripe payment_intent created",
            extra=log_extra(
                event="stripe.payment_intent.created",
                order_id=order_id,
                payment_intent_id=payment_intent.id,
            ),
        )
        return map_payment_intent(payment_intent)

    async def refund(
        self,
        order_id: int,
        payment_intent_id: str,
    ) -> StripeRefund:
        try:
            refund = await self._client.v1.refunds.create_async(
                params={
                    "payment_intent": payment_intent_id,
                    "reason": "requested_by_customer",
                },  # type: ignore[arg-type]
                options={"idempotency_key": f"refund-order-{order_id}"},
            )
        except stripe.StripeError as err:
            logger.error(
                "Stripe refund request failed",
                extra=log_extra(
                    event="stripe.refund.failed",
                    order_id=order_id,
                    payment_intent_id=payment_intent_id,
                    error=str(err),
                ),
            )
            raise StripePaymentError(str(err)) from err

        logger.info(
            "Stripe refund created",
            extra=log_extra(
                event="stripe.refund.created",
                order_id=order_id,
                payment_intent_id=payment_intent_id,
                stripe_refund_id=refund.id,
                stripe_refund_status=refund.status,
            ),
        )
        return map_refund(refund)


class MockStripeBackend:
    def __init__(self, base_url: str, secret: str) -> None:
        self._simulator = StripeWebhookSimulator(
            base_url=base_url,
            secret=secret,
        )

    async def create_payment_intent(
        self,
        amount: Decimal,
        idempotency_key: str,
        currency: str,
        metadata: dict[str, str] | None = None,
    ) -> StripePaymentIntent:
        order_id = metadata.get("order_id") if metadata else None
        payment_intent_id = f"pi_mock_{uuid4().hex[:16]}"

        logger.info(
            "Mock payment_intent created",
            extra=log_extra(
                event="stripe.mock.payment_intent.created",
                order_id=order_id,
                payment_intent_id=payment_intent_id,
            ),
        )

        asyncio.create_task(
            self._dispatch_after_delay(
                event_type="payment_intent.succeeded",
                payment_intent_id=payment_intent_id,
            )
        )

        return StripePaymentIntent(
            id=payment_intent_id,
            status="processing",
            amount=amount,
            currency=currency.lower(),
        )

    async def _dispatch_after_delay(
        self,
        *,
        event_type: str,
        payment_intent_id: str,
        delay: float = MOCK_WEBHOOK_DELAY_SECONDS,
    ) -> None:
        await asyncio.sleep(delay)
        if event_type == "payment_intent.succeeded":
            await self._simulator.dispatch_payment_intent_succeeded(payment_intent_id)
        elif event_type == "refund.created":
            await self._simulator.dispatch_refund_created(payment_intent_id)

    async def refund(
        self,
        order_id: int,
        payment_intent_id: str,
    ) -> StripeRefund:
        refund_id = f"re_mock_{uuid4().hex[:16]}"

        logger.info(
            "Mock refund created",
            extra=log_extra(
                event="stripe.mock.refund.created",
                order_id=order_id,
                payment_intent_id=payment_intent_id,
                stripe_refund_id=refund_id,
            ),
        )

        await self._simulator.dispatch_refund_created(payment_intent_id)

        return StripeRefund(
            id=refund_id,
            status="succeeded",
            payment_intent_id=payment_intent_id,
            amount=Decimal("0"),
        )


def create_stripe_backend() -> StripeBackend:
    if settings.stripe_mock_enabled:
        return MockStripeBackend(
            base_url=settings.stripe_webhook_base_url,
            secret=settings.webhook_secret_key,
        )

    return SdkStripeBackend(api_key=settings.stripe_api_key)
