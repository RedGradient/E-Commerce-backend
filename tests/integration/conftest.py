from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TypedDict
from unittest.mock import patch

import pytest
from alembic.config import Config
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from app.models.models import Order

POSTGRES_IMAGE = "postgres:16-alpine"
POSTGRES_DB = "commerce"
POSTGRES_USER = "commerce_user"
POSTGRES_PASSWORD = "commerce_pass"

REDIS_IMAGE = "redis:7-alpine"
REDIS_PORT = 6379

TABLES = ("outbox", "order_items", "orders", "products")


class OrderItemSpec(TypedDict, total=False):
    quantity: int
    unit_price: Decimal
    product_id: int
    product_name: str
    price: Decimal
    description: str | None


@dataclass(frozen=True)
class TestDatabase:
    sync_dsn: str
    async_dsn: str


@dataclass(frozen=True)
class TestRedis:
    host: str
    port: int

    @property
    def dsn(self) -> str:
        return f"redis://{self.host}:{self.port}/0"


def _configure_docker_client_env() -> None:
    if os.environ.get("DOCKER_HOST"):
        return
    for sock in (Path.home() / ".docker/run/docker.sock", Path("/var/run/docker.sock")):
        if sock.exists():
            os.environ["DOCKER_HOST"] = f"unix://{sock}"
            return


def _build_dsns(host: str, port: int) -> TestDatabase:
    return TestDatabase(
        sync_dsn=(
            f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
            f"@{host}:{port}/{POSTGRES_DB}"
        ),
        async_dsn=(
            f"postgresql+asyncpg://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
            f"@{host}:{port}/{POSTGRES_DB}"
        ),
    )


@pytest.fixture(scope="session")
def test_database() -> Generator[TestDatabase, None, None]:
    _configure_docker_client_env()

    try:
        from docker.errors import DockerException
        from testcontainers.postgres import PostgresContainer
    except ImportError as exc:
        pytest.skip(f"testcontainers is not installed: {exc}")

    try:
        with PostgresContainer(
            POSTGRES_IMAGE,
            username=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            dbname=POSTGRES_DB,
        ) as postgres:
            database = _build_dsns(
                postgres.get_container_host_ip(),
                int(postgres.get_exposed_port(5432)),
            )

            alembic_cfg = Config("alembic.ini")
            alembic_cfg.set_main_option("sqlalchemy.url", database.sync_dsn)
            command.upgrade(alembic_cfg, "head")

            yield database
    except DockerException as exc:
        pytest.skip(f"Docker is required for integration tests: {exc}")


@pytest.fixture(scope="session")
def test_redis() -> Generator[TestRedis, None, None]:
    _configure_docker_client_env()

    try:
        from docker.errors import DockerException
        from testcontainers.redis import RedisContainer
    except ImportError as exc:
        pytest.skip(f"testcontainers redis extra is not installed: {exc}")

    try:
        with RedisContainer(REDIS_IMAGE) as redis_container:
            yield TestRedis(
                host=redis_container.get_container_host_ip(),
                port=int(redis_container.get_exposed_port(REDIS_PORT)),
            )
    except DockerException as exc:
        pytest.skip(f"Docker is required for integration tests: {exc}")


@pytest.fixture(autouse=True)
async def _redis_patch(test_redis: TestRedis) -> AsyncGenerator[None, None]:
    from redis.asyncio import Redis

    from app.cache import dispose_redis
    from app.config import settings

    await dispose_redis()
    with (
        patch.object(settings, "redis_host", test_redis.host),
        patch.object(settings, "redis_port", test_redis.port),
    ):
        yield

    await dispose_redis()
    client = Redis.from_url(test_redis.dsn, decode_responses=True)
    try:
        await client.flushdb()
    finally:
        await client.aclose()


@pytest.fixture
async def _database_patch(
    test_database: TestDatabase,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    engine = create_async_engine(test_database.async_dsn, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    with (
        patch("app.infra.get_or_create_db_engine", return_value=engine),
        patch("app.session.get_sessionmaker", return_value=session_factory),
        patch(
            "app.workers.order_cancellator.get_sessionmaker",
            return_value=session_factory,
        ),
    ):
        yield session_factory

    await engine.dispose()


@pytest.fixture
async def db_session(
    _database_patch: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with _database_patch() as session:
        try:
            yield session
        finally:
            await session.rollback()
            for table in TABLES:
                await session.execute(
                    text(f"TRUNCATE {table} RESTART IDENTITY CASCADE")
                )
            await session.commit()


async def _resolve_product(
    session: AsyncSession,
    item: OrderItemSpec,
):
    from app.models.models import Product

    if product_id := item.get("product_id"):
        product = await session.get(Product, product_id)
        if product is None:
            raise ValueError(f"product_id={product_id} not found")
        return product

    product_name = item.get("product_name")
    price = item.get("price")
    if product_name is None or price is None:
        raise ValueError("item must include product_id or product_name and price")

    product = Product(
        product_name=product_name,
        description=item.get("description"),
        price=price,
    )
    session.add(product)
    await session.flush()
    return product


@pytest.fixture
async def order_factory(
    db_session: AsyncSession,
) -> AsyncGenerator[Callable[..., Awaitable[Order]], None]:
    from app.models.models import Order, OrderItem, OrderStatus

    async def factory(**kwargs) -> Order:
        items_data: list[OrderItemSpec] | None = kwargs.pop("items", None)

        order = Order(
            status=kwargs.get("status", OrderStatus.Created),
            payment_intent_id=kwargs.get("payment_intent_id"),
            paid_at=kwargs.get("paid_at"),
            refunded_at=kwargs.get("refunded_at"),
        )
        if "created_at" in kwargs:
            order.created_at = kwargs["created_at"]

        db_session.add(order)
        await db_session.flush()

        if items_data:
            for item_data in items_data:
                product = await _resolve_product(db_session, item_data)
                quantity = item_data.get("quantity", 1)
                unit_price = item_data.get("unit_price", product.price)
                db_session.add(
                    OrderItem(
                        order_id=order.id,
                        product_id=product.id,
                        quantity=quantity,
                        unit_price=unit_price,
                    )
                )

        await db_session.commit()
        await db_session.refresh(order)

        return order

    yield factory


@pytest.fixture
async def stripe_webhook_asgi(
    db_session: AsyncSession,
) -> AsyncGenerator[None, None]:
    import json
    import logging
    import time
    from uuid import uuid4

    import httpx

    from app.integrations.stripe.webhook_simulator import (
        StripeWebhookSimulator,
        build_stripe_signature,
    )
    from app.logging_context import log_extra
    from app.routers import webhooks
    from app.session import get_db_session

    app = FastAPI()
    app.include_router(webhooks.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db
    transport = ASGITransport(app=app)
    logger = logging.getLogger("app.integrations.stripe.webhook_simulator")

    async def asgi_dispatch(
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
        payload_bytes = json.dumps(event).encode("utf-8")
        signature = build_stripe_signature(payload_bytes, self._secret)

        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            timeout=10.0,
        ) as client:
            response = await client.post(
                "/webhooks/stripe",
                content=payload_bytes,
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

    with patch.object(StripeWebhookSimulator, "_dispatch", asgi_dispatch):
        yield

    app.dependency_overrides.clear()


@pytest.fixture
async def webhook_client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    from app.routers import webhooks
    from app.session import get_db_session

    app = FastAPI()
    app.include_router(webhooks.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db_session] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://localhost:8000"
    ) as client:
        yield client

    app.dependency_overrides.clear()
