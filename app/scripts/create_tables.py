import asyncio

from app.infra import dispose_engine, get_or_create_db_engine
from app.models.models import Base


async def create_tables() -> None:
    engine = get_or_create_db_engine()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    await dispose_engine()
    print("Tables created")


if __name__ == "__main__":
    asyncio.run(create_tables())
