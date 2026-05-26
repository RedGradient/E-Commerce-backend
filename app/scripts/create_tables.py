import asyncio
import logging

from app.infra import dispose_engine, get_or_create_db_engine
from app.log_config import configure_logging
from app.logging_context import log_extra
from app.models.models import Base

configure_logging()
logger = logging.getLogger(__name__)


async def create_tables() -> None:
    engine = get_or_create_db_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await dispose_engine()
    logger.info("Database tables created", extra=log_extra(event="db.tables.created"))


if __name__ == "__main__":
    asyncio.run(create_tables())
