from decimal import Decimal

from app.integrations.stripe.models import StripePaymentIntent, StripeRefund


def map_payment_intent(payment_intent) -> StripePaymentIntent:
    return StripePaymentIntent(
        id=payment_intent.id,
        status=payment_intent.status,
        amount=Decimal(payment_intent.amount) / 100,
        currency=payment_intent.currency,
    )


def map_refund(refund) -> StripeRefund:
    refunded_payment_intent = refund.payment_intent
    if isinstance(refunded_payment_intent, str):
        payment_intent_id = refunded_payment_intent
    elif refunded_payment_intent is None:
        payment_intent_id = None
    else:
        payment_intent_id = refunded_payment_intent.id

    return StripeRefund(
        id=refund.id,
        status=refund.status,
        payment_intent_id=payment_intent_id,
        amount=Decimal(refund.amount) / 100,
    )
