import json
from typing import Any

from redis.asyncio import Redis

from app.config import settings

_redis_client: Redis | None = None


def get_or_create_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(
            settings.redis_dsn, encoding="utf-8", decode_responses=True
        )
    return _redis_client


async def dispose_redis():
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


IDEMPOTENCY_PREFIX = "idempotency:checkout:"


async def reserve_idempotency(
    key: str, ttl_seconds: int = settings.default_idempotency_ttl_seconds
) -> bool:
    redis = get_or_create_redis_client()
    redis_key = build_idempotency_key(key)

    result = await redis.set(
        redis_key,
        json.dumps({"status": "processing"}),
        nx=True,
        ex=ttl_seconds,
    )
    return bool(result)


async def save_idempotency_result(
    key: str,
    payload: dict[str, Any],
    ttl_seconds: int = settings.default_idempotency_ttl_seconds,
) -> None:
    redis = get_or_create_redis_client()
    redis_key = build_idempotency_key(key)

    await redis.set(
        redis_key,
        json.dumps({"status": "completed", "payload": payload}),
        ex=ttl_seconds,
    )


async def get_idempotency_result(key: str) -> dict | None:
    redis = get_or_create_redis_client()
    redis_key = build_idempotency_key(key)

    raw = await redis.get(redis_key)
    if raw is None:
        return None
    return json.loads(raw)


def build_idempotency_key(raw_key: str) -> str:
    return f"{IDEMPOTENCY_PREFIX}{raw_key}"


async def release_idempotency_key(key: str) -> None:
    redis = get_or_create_redis_client()
    await redis.delete(build_idempotency_key(key))
