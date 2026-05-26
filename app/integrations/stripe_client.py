import logging
from decimal import ROUND_HALF_UP, Decimal

import httpx
from pydantic import BaseModel

from app.config import settings
from app.logging_context import log_extra

logger = logging.getLogger(__name__)


class StripePaymentIntent(BaseModel):
    id: str
    status: str
    amount: Decimal
    currency: str


class StripePaymentError(Exception):
    def __init__(self, *args: object) -> None:
        super().__init__(*args)


class StripeClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=settings.stripe_base_url,
            headers={"Authorization": f"Bearer {settings.stripe_api_key}"},
            timeout=10.0,
        )

    async def healthcheck(self) -> bool:
        return True

    async def close(self) -> None:
        await self._client.aclose()

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

        payload = {
            "amount": amount_cents,
            "currency": currency.lower(),
            "metadata[order_id]": order_id,
            "payment_method": "pm_card_visa",
            "confirm": "true",
            "automatic_payment_methods[enabled]": "true",
            "automatic_payment_methods[allow_redirects]": "never",
        }

        response = await self._client.post(
            url="/v1/payment_intents",
            data=payload,
            headers={"Idempotency-Key": idempotency_key},
        )

        if not response.is_success:
            message = response.json().get("error", {}).get("message", response.text)
            logger.error(
                "Stripe payment_intent request failed",
                extra=log_extra(
                    event="stripe.payment_intent.failed",
                    order_id=order_id,
                    http_status=response.status_code,
                    error=message,
                ),
            )
            raise StripePaymentError(message)

        data = response.json()
        payment_intent = StripePaymentIntent(
            id=data["id"],
            status=data["status"],
            amount=Decimal(int(data["amount"])) / 100,
            currency=data["currency"],
        )

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
            raise StripePaymentError

        logger.info(
            "Stripe payment_intent created",
            extra=log_extra(
                event="stripe.payment_intent.created",
                order_id=order_id,
                payment_intent_id=payment_intent.id,
            ),
        )
        return payment_intent
