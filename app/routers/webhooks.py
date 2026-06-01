import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from stripe import Event, SignatureVerificationError, Webhook

from app.config import settings
from app.domain.order_state_machine import (
    TransitionOutcome,
    apply_payment_succeeded,
    apply_refund,
)
from app.events import ORDER_PAID, ORDER_REFUNDED
from app.logging_context import log_extra, update_log_context
from app.models.models import Order
from app.models.outbox import Outbox
from app.observability.metrics import record_webhook_event
from app.services.checkout import build_checkout_payload
from app.services.refund import build_refund_payload
from app.session import get_db_session

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


def _is_outbox_dedup_hit(err: IntegrityError) -> bool:
    return "uq_outbox_dedup_key" in str(err.orig)


def outbox_checkout_message(order: Order, dedup_key: str) -> Outbox:
    return Outbox(
        event_type=ORDER_PAID,
        dedup_key=dedup_key,
        order_id=order.id,
        payload=build_checkout_payload(order),
        created_at=datetime.now(UTC),
    )


def outbox_refund_message(
    order: Order,
    *,
    refunded_at: datetime,
    dedup_key: str,
) -> Outbox:
    return Outbox(
        event_type=ORDER_REFUNDED,
        dedup_key=dedup_key,
        order_id=order.id,
        payload=build_refund_payload(order, refunded_at=refunded_at),
        created_at=datetime.now(UTC),
    )


@router.post("/stripe", status_code=200)
async def webhook_stripe(
    request: Request,
    stripe_signature: str = Header(alias="Stripe-Signature"),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        event = Webhook.construct_event(
            payload=await request.body(),
            sig_header=stripe_signature,
            secret=settings.webhook_secret_key,
        )
    except SignatureVerificationError:
        record_webhook_event(event_type="stripe", outcome="signature_invalid")
        logger.warning(
            "Stripe webhook signature verification failed",
            extra=log_extra(event="stripe.webhook.signature_invalid"),
        )
        return Response(content="Ошибка проверки подписи.", status_code=400)

    update_log_context(
        stripe_event_id=event.id,
        stripe_event_type=event.type,
    )
    logger.info(
        "Stripe webhook received",
        extra=log_extra(event="stripe.webhook.received"),
    )

    if event.type == "payment_intent.succeeded":
        return await handle_payment_intent_succeeded(event, session)
    if event.type == "refund.created":
        return await handle_payment_refunded(event, session)

    record_webhook_event(event_type=event.type, outcome="ignored")
    logger.debug(
        "Stripe webhook ignored",
        extra=log_extra(event="stripe.webhook.ignored"),
    )
    return {"result": "OK"}


async def handle_payment_intent_succeeded(
    event: Event,
    session: AsyncSession,
) -> dict[str, str]:
    pi = event.data.object
    pi_id = pi.id
    update_log_context(payment_intent_id=pi_id)

    order = await find_order_by_intent_id(session, pi_id)

    if order is None:
        record_webhook_event(
            event_type="payment_intent.succeeded",
            outcome="order_missing",
        )
        logger.warning(
            "No order for payment_intent.succeeded",
            extra=log_extra(event="stripe.webhook.payment_succeeded.order_missing"),
        )
        return {"result": "OK"}
    update_log_context(order_id=order.id)

    paid_at = datetime.fromtimestamp(event.created, tz=UTC)
    result = apply_payment_succeeded(
        order,
        payment_intent_id=pi_id,
        paid_at=paid_at,
    )

    if result.outcome is TransitionOutcome.REJECTED:
        record_webhook_event(
            event_type="payment_intent.succeeded",
            outcome="rejected",
        )
        logger.debug(
            "Skipping payment_intent.succeeded for order state",
            extra=log_extra(
                event="stripe.webhook.payment_succeeded.skipped",
                order_status=result.from_status.value,
            ),
        )
        return {"result": "OK"}

    if result.outcome is TransitionOutcome.NOOP:
        record_webhook_event(
            event_type="payment_intent.succeeded",
            outcome="noop",
        )
        logger.debug(
            "Idempotent skip payment_intent.succeeded",
            extra=log_extra(
                event="stripe.webhook.payment_succeeded.idempotent",
                order_status=result.from_status.value,
            ),
        )
        return {"result": "OK"}

    dedup_key = f"stripe:{event.id}"
    try:
        session.add(outbox_checkout_message(order, dedup_key))
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        if _is_outbox_dedup_hit(err):
            record_webhook_event(
                event_type="payment_intent.succeeded",
                outcome="dedup",
            )
            logger.info(
                "Outbox dedup hit for paid event",
                extra=log_extra(
                    event="outbox.dedup_hit",
                    dedup_key=dedup_key,
                    dedup_scope=ORDER_PAID,
                ),
            )
            return {"result": "OK"}
        logger.exception(
            "Failed to persist outbox message for paid event",
            extra=log_extra(
                event="outbox.persist_failed",
                dedup_key=dedup_key,
                dedup_scope=ORDER_PAID,
                db_error=str(err.orig),
            ),
        )
        raise

    record_webhook_event(
        event_type="payment_intent.succeeded",
        outcome="applied",
    )
    logger.info(
        "Order marked Paid from webhook",
        extra=log_extra(event="order.paid.webhook"),
    )
    return {"result": "OK"}


async def handle_payment_refunded(
    event: Event,
    session: AsyncSession,
) -> dict[str, str]:
    refund = event.data.object
    pi_id = getattr(refund, "payment_intent", None)
    if not pi_id:
        record_webhook_event(event_type="refund.created", outcome="invalid_payload")
        logger.warning(
            "refund.created missing payment_intent",
            extra=log_extra(event="stripe.webhook.refund.missing_payment_intent"),
        )
        return {"result": "OK"}

    update_log_context(payment_intent_id=pi_id)
    order = await find_order_by_intent_id(session, pi_id)

    if order is None:
        record_webhook_event(event_type="refund.created", outcome="order_missing")
        logger.warning(
            "No order for refund.created",
            extra=log_extra(event="stripe.webhook.refund.order_missing"),
        )
        return {"result": "OK"}
    update_log_context(order_id=order.id)

    refunded_at = datetime.fromtimestamp(event.created, tz=UTC)
    result = apply_refund(order, refunded_at=refunded_at)

    if result.outcome is TransitionOutcome.REJECTED:
        record_webhook_event(event_type="refund.created", outcome="rejected")
        logger.info(
            "Skipping refund.created for order state",
            extra=log_extra(
                event="stripe.webhook.refund.skipped",
                order_status=result.from_status.value,
            ),
        )
        return {"result": "OK"}

    if result.outcome is TransitionOutcome.NOOP:
        record_webhook_event(event_type="refund.created", outcome="noop")
        logger.debug(
            "Idempotent skip refund.created",
            extra=log_extra(event="stripe.webhook.refund.idempotent"),
        )
        return {"result": "OK"}

    dedup_key = f"stripe:{event.id}"
    try:
        session.add(
            outbox_refund_message(
                order,
                refunded_at=refunded_at,
                dedup_key=dedup_key,
            )
        )
        await session.commit()
    except IntegrityError as err:
        await session.rollback()
        if _is_outbox_dedup_hit(err):
            record_webhook_event(event_type="refund.created", outcome="dedup")
            logger.info(
                "Outbox dedup hit for refunded event",
                extra=log_extra(
                    event="outbox.dedup_hit",
                    dedup_key=dedup_key,
                    dedup_scope=ORDER_REFUNDED,
                ),
            )
            return {"result": "OK"}
        logger.exception(
            "Failed to persist outbox message for refunded event",
            extra=log_extra(
                event="outbox.persist_failed",
                dedup_key=dedup_key,
                dedup_scope=ORDER_REFUNDED,
                db_error=str(err.orig),
            ),
        )
        raise

    record_webhook_event(event_type="refund.created", outcome="applied")
    logger.info(
        "Order marked Refunded from webhook",
        extra=log_extra(event="order.refunded.webhook"),
    )
    return {"result": "OK"}


async def find_order_by_intent_id(session: AsyncSession, pi_id: str) -> Order | None:
    stmt = select(Order).where(Order.payment_intent_id == pi_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()
