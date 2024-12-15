import os
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession


def _get_url() -> str:
    if url := os.getenv("DB_URL", None):
        return url
    else:
        username = os.environ["DB_USER"]
        password = os.environ["DB_PASS"]
        host = os.environ["DB_HOST"]
        port = os.environ["DB_PORT"]
        db_name = os.environ["DB_NAME"]
        return f"postgresql+asyncpg://{username}:{password}@{host}:{port}/{db_name}"


DATABASE_URL = _get_url()
engine = create_async_engine(DATABASE_URL)
AsyncSessionMaker = async_sessionmaker(bind=engine)


async def get_session() -> AsyncSession:
    async with AsyncSessionMaker() as session:
        yield session
