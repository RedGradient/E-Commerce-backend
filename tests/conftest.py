import os
from collections.abc import AsyncGenerator, Awaitable, Callable

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infra import dispose_engine
from app.models.models import Order, OrderStatus
from app.routers import webhooks
from app.session import get_db_session, get_sessionmaker, reset_sessionmaker

os.environ["ENV_FILE"] = ".env.test"

TABLES = ("outbox", "order_items", "orders", "products")


async def _reset_db_pool() -> None:
    """Drop engine pool so the next test binds asyncpg to its own event loop."""
    await dispose_engine()
    reset_sessionmaker()


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    await _reset_db_pool()
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
    await _reset_db_pool()


@pytest.fixture
async def order_factory(
    db_session: AsyncSession,
) -> AsyncGenerator[Callable[..., Awaitable[Order]], None]:
    async def factory(**kwargs) -> Order:
        order = Order(
            status=kwargs.get("status", OrderStatus.Created),
            payment_intent_id=kwargs.get("payment_intent_id"),
            paid_at=kwargs.get("paid_at"),
            refunded_at=kwargs.get("refunded_at"),
        )

        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        return order

    yield factory


@pytest.fixture
async def webhook_client(db_session) -> AsyncGenerator[AsyncClient, None]:
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
