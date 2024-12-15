import asyncio
import os
import subprocess
import time

import asyncpg
import httpx
import pytest
import shortuuid
from testcontainers.postgres import PostgresContainer

from wizard.common import project_root


async def check_db(dsn: str, retry_cnt: int = 10):
    for attempt in range(retry_cnt):
        try:
            conn = await asyncpg.connect(dsn=dsn)
            await conn.execute('SELECT 1')
            await conn.close()
            return
        except (asyncpg.exceptions.CannotConnectNowError, OSError,
                asyncpg.PostgresError, asyncpg.exceptions.ConnectionDoesNotExistError):
            await asyncio.sleep(1)
    raise RuntimeError("Postgres container failed to become healthy in time.")


@pytest.fixture(scope="session")
async def db_url() -> str:
    driver = "asyncpg"
    with PostgresContainer("postgres:17-alpine", driver=driver) as postgres:
        url = postgres.get_connection_url()
        await check_db(postgres.get_connection_url(driver=None))
        yield url


@pytest.fixture(scope="session")
def base_url(db_url: str) -> str:
    base_url = "http://127.0.0.1:8000/api/v1"

    def health_check() -> bool:
        try:
            with httpx.Client(base_url=base_url, timeout=3) as client:
                response: httpx.Response = client.get("/health")
            response.raise_for_status()
            return True
        except httpx.ConnectError:
            return False

    if not health_check():
        os.environ["DB_URL"] = db_url
        env: dict = os.environ.copy()
        cwd: str = project_root.path()
        process = subprocess.Popen(["uvicorn", "mbw.api:app"], cwd=cwd, env=env)

        while not health_check():  # 等待服务起来
            if process.poll() is not None:
                raise RuntimeError(f"Process exit with code {process.returncode}")
            time.sleep(1)

        yield base_url

        process.terminate()
        process.wait()
    else:
        yield base_url


@pytest.fixture(scope="session")
async def namespace_id(base_url: str) -> str:
    from wizard.db.entity import NamespaceConfig
    from wizard.db import AsyncSessionMaker
    async with AsyncSessionMaker() as session:
        namespace_config = NamespaceConfig(namespace_id=shortuuid.uuid(), max_concurrency=1)
        session.add(namespace_config)
        await session.commit()
        await session.refresh(namespace_config)
    yield namespace_config.namespace_id
