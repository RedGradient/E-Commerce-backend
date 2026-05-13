from typing import Any

import aio_pika
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import settings

_engine: AsyncEngine | None = None


def get_or_create_db_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(settings.postgres_dsn, pool_pre_ping=True)
    return _engine


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def check_postgres(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


async def check_redis(redis: Redis) -> None:
    pong: Any = await redis.ping()
    if not pong:
        raise RuntimeError("redis ping failed")


async def check_rabbit(connection: aio_pika.abc.AbstractRobustConnection) -> None:
    channel = await connection.channel()
    await channel.close()
