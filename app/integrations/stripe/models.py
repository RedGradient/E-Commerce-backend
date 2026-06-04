from decimal import Decimal

from pydantic import BaseModel


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
