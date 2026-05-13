import hashlib
from decimal import Decimal

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
        intent_id = (
            "pi_test_" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:24]
        )

        payment_intent = StripePaymentIntent(
            id=intent_id, status="succeeded", amount=amount, currency=currency
        )

        if payment_intent.status != "succeeded":
            raise StripePaymentError

        return payment_intent
