from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.infra import get_or_create_db_engine

_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_sessionmaker():
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_or_create_db_engine(), expire_on_commit=False
        )
    return _sessionmaker


def reset_sessionmaker() -> None:
    global _sessionmaker
    _sessionmaker = None


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with get_sessionmaker()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
