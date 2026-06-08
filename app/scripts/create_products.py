import asyncio
import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra import dispose_engine
from app.log_config import configure_logging
from app.models.models import Product
from app.session import get_sessionmaker

configure_logging()
logger = logging.getLogger(__name__)

DEFAULT_PRODUCTS = [
    {
        "product_name": "Wireless Bluetooth Mouse",
        "description": "Ergonomic mouse with 2.4 GHz dongle and Bluetooth 5.0.",
        "price": Decimal("29.99"),
    },
    {
        "product_name": "USB-C Charging Cable 2m",
        "description": "Braided cable with 100 W Power Delivery support.",
        "price": Decimal("14.99"),
    },
    {
        "product_name": "Python Crash Course eBook",
        "description": "Digital download, 350 pages for beginners.",
        "price": Decimal("24.99"),
    },
    {
        "product_name": "Noise-Cancelling Earbuds",
        "description": "In-ear ANC, 30-hour battery life with charging case.",
        "price": Decimal("79.99"),
    },
    {
        "product_name": "Bamboo Desk Organizer",
        "description": "Tray with pen holder and phone stand for home office.",
        "price": Decimal("34.99"),
    },
]


async def create_products(session: AsyncSession) -> None:
    created = 0
    for item in DEFAULT_PRODUCTS:
        exists = await session.scalar(
            select(Product.id).where(Product.product_name == item["product_name"])
        )
        if exists:
            continue
        session.add(Product(**item))
        created += 1

    if created:
        await session.commit()
        logger.info("Products seeded", extra={"created": created})
    else:
        logger.info("Products already seeded, nothing to do")


async def main() -> None:
    async with get_sessionmaker()() as session:
        await create_products(session)
    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
