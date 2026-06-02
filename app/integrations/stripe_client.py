import logging
from decimal import ROUND_HALF_UP, Decimal

import stripe
from pydantic import BaseModel

from app.config import settings
from app.logging_context import log_extra

logger = logging.getLogger(__name__)


class StripePaymentIntent(BaseModel):
    id: str
    status: str
    amount: Decimal
    currency: str


class StripeRefund(BaseModel):
    id: str
    status: str | None
    payment_intent_id: str | None
    amount: Decimal


class StripePaymentError(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class StripeClient:
    def __init__(self) -> None:
        self._client = stripe.StripeClient(api_key=settings.stripe_api_key)

    async def healthcheck(self) -> bool:
        return True

    async def close(self) -> None:
        return None

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

        return StripePaymentIntent(
            id=payment_intent.id,
            status=payment_intent.status,
            amount=Decimal(payment_intent.amount) / 100,
            currency=payment_intent.currency,
        )

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
                },  # type: ignore
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

        refunded_payment_intent = refund.payment_intent
        if isinstance(refunded_payment_intent, str):
            resolved_payment_intent_id = refunded_payment_intent
        elif refunded_payment_intent is None:
            resolved_payment_intent_id = None
        else:
            resolved_payment_intent_id = refunded_payment_intent.id

        return StripeRefund(
            id=refund.id,
            status=refund.status,
            payment_intent_id=resolved_payment_intent_id,
            amount=Decimal(refund.amount) / 100,
        )
