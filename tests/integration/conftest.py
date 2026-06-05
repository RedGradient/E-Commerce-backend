from __future__ import annotations

import os
from collections.abc import AsyncGenerator, Awaitable, Callable, Generator
from dataclasses import dataclass
from pathlib import Path
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

TABLES = ("outbox", "order_items", "orders", "products")


@dataclass(frozen=True)
class TestDatabase:
    sync_dsn: str
    async_dsn: str


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


@pytest.fixture
async def order_factory(
    db_session: AsyncSession,
) -> AsyncGenerator[Callable[..., Awaitable[Order]], None]:
    from app.models.models import Order, OrderStatus

    async def factory(**kwargs) -> Order:
        order = Order(
            status=kwargs.get("status", OrderStatus.Created),
            payment_intent_id=kwargs.get("payment_intent_id"),
            paid_at=kwargs.get("paid_at"),
            refunded_at=kwargs.get("refunded_at"),
        )
        if "created_at" in kwargs:
            order.created_at = kwargs["created_at"]

        db_session.add(order)
        await db_session.commit()
        await db_session.refresh(order)

        return order

    yield factory


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
