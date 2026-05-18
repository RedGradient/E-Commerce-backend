import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select

from app.messaging import (
    ORDER_CANCELLED_ROUTING_KEY,
    ORDER_PAID_ROUTING_KEY,
    publish_order_cancelled,
    publish_order_paid,
)
from app.models.models import Order  # noqa: F401
from app.models.outbox import Outbox
from app.session import get_sessionmaker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__file__)

MAX_ATTEMPTS: int = 5


async def publish_by_event(event_type: str, payload: dict) -> bool:
    if event_type == ORDER_PAID_ROUTING_KEY:
        await publish_order_paid(payload)
    elif event_type == ORDER_CANCELLED_ROUTING_KEY:
        await publish_order_cancelled(payload)
    else:
        return False
    return True


def mark_as_failed(msg, error: str) -> None:
    msg.last_error = error
    msg.failed_at = datetime.now(UTC)


async def main():
    while True:
        async with get_sessionmaker()() as session:
            published_any = False

            stmt = (
                select(Outbox)
                .where(Outbox.published_at.is_(None))
                .where(Outbox.failed_at.is_(None))
                .order_by(Outbox.id)
                .limit(50)
                .with_for_update(skip_locked=True)
            )

            async with session.begin():
                messages = (await session.execute(stmt)).scalars().all()

                for msg in messages:
                    try:
                        if not await publish_by_event(msg.event_type, msg.payload):
                            warn_message = f"unknown event_type {msg.event_type}"
                            logger.warning(warn_message)
                            mark_as_failed(msg, warn_message)
                            continue
                    except Exception:
                        msg.attempts += 1

                        error_msg = (
                            f"failed to publish "
                            f"outbox_id={msg.id} "
                            f"event_type={msg.event_type}"
                        )
                        logger.exception(error_msg)

                        if msg.attempts >= MAX_ATTEMPTS:
                            mark_as_failed(msg, error_msg)
                        continue

                    msg.published_at = datetime.now(UTC)
                    logger.info(
                        "Published event %s for order with id %s",
                        msg.event_type,
                        msg.order_id,
                    )
                    published_any = True

            if not published_any:
                await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
