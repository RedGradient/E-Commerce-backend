import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, status

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
from app.log_config import configure_logging
from app.logging_context import log_extra
from app.messaging import dispose_rabbit, get_or_create_rabbit_connection
from app.middleware.prometheus_middleware import PrometheusMiddleware
from app.middleware.request_logging import RequestLoggingMiddleware
from app.routers import metrics, orders, products, webhooks

configure_logging()
logger = logging.getLogger(__name__)


async def connect_rabbit_with_retry(retries: int = 15, delay_seconds: int = 2):
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return await get_or_create_rabbit_connection()
        except Exception as exc:  # noqa: BLE001 - startup retry should catch transport failures
            last_error = exc
            logger.warning(
                "RabbitMQ connection attempt failed",
                extra=log_extra(
                    event="app.rabbitmq.connect_retry",
                    attempt=attempt,
                    max_attempts=retries,
                    error=str(exc),
                ),
            )
            if attempt == retries:
                break
            await asyncio.sleep(delay_seconds)
    raise RuntimeError("failed to connect to RabbitMQ during startup") from last_error


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Application starting",
        extra=log_extra(event="app.startup.begin"),
    )
    app.state.db_engine = get_or_create_db_engine()
    app.state.redis = get_or_create_redis_client()
    app.state.rabbit = await connect_rabbit_with_retry()
    app.state.stripe = StripeClient()
    logger.info(
        "Application startup complete",
        extra=log_extra(event="app.startup.complete"),
    )
    yield
    logger.info(
        "Application shutting down",
        extra=log_extra(event="app.shutdown.begin"),
    )
    await dispose_engine()
    await dispose_redis()
    await dispose_rabbit()

    logger.info(
        "Application shutdown complete",
        extra=log_extra(event="app.shutdown.complete"),
    )


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(PrometheusMiddleware)
app.include_router(metrics.router)
app.include_router(orders.router)
app.include_router(products.router)
app.include_router(webhooks.router)
register_exception_handlers(app)


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


async def _run_readiness_check(name: str, check) -> None:
    try:
        await check()
    except Exception as exc:
        logger.error(
            "Readiness check failed",
            extra=log_extra(event="health.ready.failed", check=name),
            exc_info=exc,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{name} unavailable",
        ) from exc


@app.get("/health/ready")
async def ready() -> dict[str, str]:
    await _run_readiness_check(
        "postgres",
        lambda: check_postgres(app.state.db_engine),
    )
    await _run_readiness_check(
        "redis",
        lambda: check_redis(app.state.redis),
    )
    await _run_readiness_check(
        "rabbitmq",
        lambda: check_rabbit(app.state.rabbit),
    )

    stripe_ok = await app.state.stripe.healthcheck()
    if not stripe_ok:
        logger.error(
            "Readiness check failed",
            extra=log_extra(event="health.ready.failed", check="stripe"),
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="stripe unavailable",
        )

    logger.debug(
        "Readiness checks passed",
        extra=log_extra(event="health.ready.ok"),
    )
    return {"status": "ready"}
