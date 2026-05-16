from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from stripe import SignatureVerificationError, Webhook

from app.config import settings
from app.models.models import Order, OrderStatus
from app.models.outbox import Outbox
from app.services.checkout import build_checkout_payload
from app.session import get_db_session

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


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

    if event.type != "payment_intent.succeeded":
        return {"result": "OK"}

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
