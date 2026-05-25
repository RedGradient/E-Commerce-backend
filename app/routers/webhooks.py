import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from stripe import Event, SignatureVerificationError, Webhook

from app.config import settings
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
        return Response(content="Ошибка проверки подписи.", status_code=400)

    if event.type == "payment_intent.succeeded":
        return await handle_payment_intent_succeeded(event, session)
    if event.type == "refund.created":
        return await handle_payment_refunded(event, session)

    return {"result": "OK"}


async def handle_payment_intent_succeeded(
    event: Event,
    session: AsyncSession,
) -> dict[str, str]:
    pi = event.data.object
    pi_id = pi.id

    order = await find_order_by_intent_id(session, pi_id)

    # --- Validation ---
    if order is None:
        return {"result": "OK"}
    if order.status == OrderStatus.Created:
        return {"result": "OK"}
    if order.status == OrderStatus.Paid:
        if order.payment_intent_id == pi_id:
            return {"result": "OK"}
        return {"result": "OK"}

    apply_order_paid(
        order, pi_id, paid_at=datetime.fromtimestamp(event.created, tz=UTC)
    )

    session.add(outbox_checkout_message(order))

    await session.commit()

    return {"result": "OK"}


async def handle_payment_refunded(
    event: Event,
    session: AsyncSession,
) -> dict[str, str]:
    refund = event.data.object
    pi_id = getattr(refund, "payment_intent", None)
    if not pi_id:
        return {"result": "OK"}

    order = await find_order_by_intent_id(session, pi_id)

    if order is None:
        return {"result": "OK"}
    if order.status == OrderStatus.Refunded:
        return {"result": "OK"}
    if order.status != OrderStatus.Paid:
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
