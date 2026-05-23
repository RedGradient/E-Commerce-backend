import os
from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.models import Order, OrderStatus
from app.routers import webhooks
from app.session import get_db_session, get_sessionmaker

os.environ["ENV_FILE"] = ".env.test"


@pytest.fixture
def order_factory(db_session: AsyncSession) -> Callable[..., Awaitable[Order]]:
    async def factory(**kwargs) -> Order:
        order = Order(
            id=kwargs.get("id"),
            status=kwargs.get(
                "status",
                OrderStatus.Created,
            ),
            payment_intent_id=kwargs.get(
                "payment_intent_id",
            ),
        )

        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        return order

    return factory


TABLES = ("outbox", "order_items", "orders", "products")  # порядок: сначала зависимые


@pytest.fixture
async def db_session():
    async with get_sessionmaker()() as session:
        try:
            yield session
        finally:
            await session.rollback()
            for table in TABLES:
                await session.execute(
                    text(f"TRUNCATE {table} RESTART IDENTITY CASCADE")
                )
            await session.commit()


@pytest.fixture
async def webhook_client(db_session) -> AsyncGenerator[AsyncClient]:
    app = FastAPI()
    app.include_router(webhooks.router)

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://localhost:8000"
    ) as client:
        yield client

    app.dependency_overrides.clear()
