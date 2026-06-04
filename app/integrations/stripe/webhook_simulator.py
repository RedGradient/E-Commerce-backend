import hashlib
import hmac
import json
import logging
import time
from uuid import uuid4

import httpx

from app.logging_context import log_extra

logger = logging.getLogger(__name__)


def build_stripe_signature(
    payload: bytes,
    secret: str,
    *,
    timestamp: int | None = None,
) -> str:
    ts = timestamp if timestamp is not None else int(time.time())
    signed_payload = f"{ts}.".encode() + payload
    digest = hmac.new(
        secret.encode("utf-8"),
        signed_payload,
        hashlib.sha256,
    ).hexdigest()
    return f"t={ts},v1={digest}"


class StripeWebhookSimulator:
    def __init__(self, *, base_url: str, secret: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret = secret

    async def dispatch_payment_intent_succeeded(self, payment_intent_id: str) -> None:
        await self._dispatch(
            event_type="payment_intent.succeeded",
            data_object={
                "id": payment_intent_id,
                "object": "payment_intent",
                "status": "succeeded",
            },
            payment_intent_id=payment_intent_id,
        )

    async def dispatch_refund_created(self, payment_intent_id: str) -> None:
        await self._dispatch(
            event_type="refund.created",
            data_object={
                "id": f"re_mock_{uuid4().hex[:16]}",
                "object": "refund",
                "payment_intent": payment_intent_id,
                "status": "succeeded",
            },
            payment_intent_id=payment_intent_id,
        )

    async def _dispatch(
        self,
        *,
        event_type: str,
        data_object: dict,
        payment_intent_id: str,
    ) -> None:
        created = int(time.time())
        event = {
            "id": f"evt_mock_{uuid4().hex[:16]}",
            "object": "event",
            "type": event_type,
            "created": created,
            "data": {"object": data_object},
        }
        payload = json.dumps(event).encode("utf-8")
        signature = build_stripe_signature(payload, self._secret)

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                f"{self._base_url}/webhooks/stripe",
                content=payload,
                headers={"Stripe-Signature": signature},
            )
            response.raise_for_status()

        logger.info(
            "Stripe webhook event simulated",
            extra=log_extra(
                event=f"stripe.simulator.{event_type.replace('.', '_')}",
                stripe_event_type=event_type,
                payment_intent_id=payment_intent_id,
            ),
        )
