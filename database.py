import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@db:5432/events_db")


class Base(DeclarativeBase):
    pass


def make_engine(**kwargs):
    # asyncpg connections belong to one event loop. Celery tasks and tests start a new
    # loop each time, so they ask for NullPool and never reuse a connection across loops.
    if os.getenv("DB_NULLPOOL") == "1":
        kwargs.setdefault("poolclass", NullPool)
    return create_async_engine(DATABASE_URL, echo=os.getenv("SQL_ECHO") == "1", **kwargs)


engine = make_engine()
async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_db():
    async with async_session() as session:
        yield session
