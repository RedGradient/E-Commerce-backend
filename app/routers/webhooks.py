import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from stripe import Event, SignatureVerificationError, Webhook

from app.config import settings
from app.logging_context import log_extra, update_log_context
from app.models.models import Order, OrderStatus
from app.models.outbox import Outbox
from app.services.checkout import build_checkout_payload
from app.services.refund import apply_order_refunded, build_refund_payload
from app.session import get_db_session

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


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
        logger.warning(
            "No order for payment_intent.succeeded",
            extra=log_extra(event="stripe.webhook.payment_succeeded.order_missing"),
        )
        return {"result": "OK"}
    update_log_context(order_id=order.id)

    if order.status == OrderStatus.Created:
        logger.debug(
            "Skipping payment_intent.succeeded for Created order",
            extra=log_extra(
                event="stripe.webhook.payment_succeeded.skipped",
                order_status=order.status.value,
            ),
        )
        return {"result": "OK"}
    if order.status == OrderStatus.Paid:
        logger.debug(
            "Idempotent skip payment_intent.succeeded",
            extra=log_extra(
                event="stripe.webhook.payment_succeeded.idempotent",
                order_status=order.status.value,
            ),
        )
        return {"result": "OK"}

    apply_order_paid(
        order, pi_id, paid_at=datetime.fromtimestamp(event.created, tz=UTC)
    )

    session.add(outbox_checkout_message(order))

    await session.commit()

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
        logger.warning(
            "refund.created missing payment_intent",
            extra=log_extra(event="stripe.webhook.refund.missing_payment_intent"),
        )
        return {"result": "OK"}

    update_log_context(payment_intent_id=pi_id)
    order = await find_order_by_intent_id(session, pi_id)

    if order is None:
        logger.warning(
            "No order for refund.created",
            extra=log_extra(event="stripe.webhook.refund.order_missing"),
        )
        return {"result": "OK"}
    update_log_context(order_id=order.id)

    if order.status == OrderStatus.Refunded:
        logger.debug(
            "Idempotent skip refund.created",
            extra=log_extra(event="stripe.webhook.refund.idempotent"),
        )
        return {"result": "OK"}
    if order.status != OrderStatus.Paid:
        logger.info(
            "Skipping refund.created for non-Paid order",
            extra=log_extra(
                event="stripe.webhook.refund.skipped",
                order_status=order.status.value,
            ),
        )
        return {"result": "OK"}

    refunded_at = datetime.fromtimestamp(event.created, tz=UTC)
    apply_order_refunded(order, refunded_at)

    session.add(
        Outbox(
            event_type="order.refunded",
            order_id=order.id,
            payload=build_refund_payload(order, refunded_at=refunded_at),
            created_at=datetime.now(UTC),
        )
    )

    await session.commit()

    logger.info(
        "Order marked Refunded from webhook",
        extra=log_extra(event="order.refunded.webhook"),
    )
    return {"result": "OK"}


def outbox_checkout_message(order: Order) -> Outbox:
    return Outbox(
        event_type="order.paid",
        order_id=order.id,
        payload=build_checkout_payload(order),
        created_at=datetime.now(UTC),
    )


async def find_order_by_intent_id(session: AsyncSession, pi_id: str) -> Order | None:
    stmt = select(Order).where(Order.payment_intent_id == pi_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


def apply_order_paid(order: Order, payment_intent_id: str, paid_at: datetime) -> None:
    order.status = OrderStatus.Paid
    order.payment_intent_id = payment_intent_id
    order.paid_at = paid_at
