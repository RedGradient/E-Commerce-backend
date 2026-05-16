import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.cache import dispose_redis, get_or_create_redis_client
from app.config import settings
from app.exception_handlers import register_exception_handlers
from app.infra import (
    check_postgres,
    check_rabbit,
    check_redis,
    dispose_engine,
    get_or_create_db_engine,
)
from app.integrations.stripe_client import StripeClient
from app.messaging import dispose_rabbit, get_or_create_rabbit_connection
from app.routers import orders, products, webhooks


async def connect_rabbit_with_retry(retries: int = 15, delay_seconds: int = 2):
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return await get_or_create_rabbit_connection()
        except Exception as exc:  # noqa: BLE001 - startup retry should catch transport failures
            last_error = exc
            if attempt == retries:
                break
            await asyncio.sleep(delay_seconds)
    raise RuntimeError("failed to connect to RabbitMQ during startup") from last_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_engine = get_or_create_db_engine()
    app.state.redis = get_or_create_redis_client()
    app.state.rabbit = await get_or_create_rabbit_connection()
    app.state.stripe = StripeClient()
    yield
    await dispose_engine()
    await dispose_redis()
    await dispose_rabbit()
    await app.state.stripe.close()


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(orders.router)
app.include_router(products.router)
app.include_router(webhooks.router)
register_exception_handlers(app)


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready() -> dict[str, str]:
    await check_postgres(app.state.db_engine)
    await check_redis(app.state.redis)
    await check_rabbit(app.state.rabbit)
    stripe_ok = await app.state.stripe.healthcheck()
    if not stripe_ok:
        raise RuntimeError("stripe integration unavailable")
    return {"status": "ready"}
