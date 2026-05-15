from decimal import ROUND_HALF_UP, Decimal

import httpx
from pydantic import BaseModel

from app.config import settings


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
        # Lightweight call shape for future external API integration.
        # In a real project this should hit a provider status endpoint.
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
        order_id = None
        if metadata is not None:
            order_id = metadata["order_id"]

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
            print(message)
            raise StripePaymentError(message)

        data = response.json()
        payment_intent = StripePaymentIntent(
            id=data["id"],
            status=data["status"],
            amount=Decimal(int(data["amount"])) / 100,
            currency=data["currency"],
        )

        if payment_intent.status != "succeeded":
            raise StripePaymentError

        return payment_intent
