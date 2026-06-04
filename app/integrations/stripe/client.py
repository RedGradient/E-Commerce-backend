from decimal import Decimal

from app.integrations.stripe.backends import StripeBackend, create_stripe_backend
from app.integrations.stripe.models import StripePaymentIntent, StripeRefund


class StripeClient:
    def __init__(self, backend: StripeBackend | None = None) -> None:
        self._backend = backend or create_stripe_backend()

    async def create_payment_intent(
        self,
        amount: Decimal,
        idempotency_key: str,
        currency: str,
        metadata: dict[str, str] | None = None,
    ) -> StripePaymentIntent:
        return await self._backend.create_payment_intent(
            amount,
            idempotency_key,
            currency,
            metadata,
        )

    async def refund(
        self,
        order_id: int,
        payment_intent_id: str,
    ) -> StripeRefund:
        return await self._backend.refund(order_id, payment_intent_id)
