import asyncio
import os
from dotenv import load_dotenv
import subprocess
import time

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient
from testcontainers.postgres import PostgresContainer
from testcontainers.chroma import ChromaContainer

from common.config_loader import Loader
from wizard.api.server import app
from common import project_root
from common.logger import get_logger
from wizard.config import Config, ENV_PREFIX

logger = get_logger("fixture")


async def check_postgres_url(dsn: str, retry_cnt: int = 10):
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


@pytest.fixture(scope="function")
def postgres_url() -> str:
    driver = "asyncpg"
    with PostgresContainer(image="postgres:17-alpine", driver=driver) as postgres:
        url = postgres.get_connection_url()
        asyncio.run(check_postgres_url(postgres.get_connection_url(driver=None)))

        os.environ["MBW_DB_URL"] = url
        logger.debug({"db_url": url, "env": {"MBW_DB_URL": os.getenv("MBW_DB_URL")}})

        yield url

@pytest.fixture(scope="function")
def chromadb_endpoint() -> str:
    with ChromaContainer(image="chromadb/chroma:0.5.23") as chromadb:
        server_info: dict = chromadb.get_config()
        endpoint: str = server_info["endpoint"]
        def check_chromadb_ready() -> bool:
            for i in range(10):
                try:
                    with httpx.Client(base_url=f"http://{endpoint}", timeout=3) as client:  # noqa
                        response: httpx.Response = client.get("/api/v1/heartbeat")
                    response.raise_for_status()
                    return True
                except httpx.ConnectError:
                    time.sleep(1)
            raise RuntimeError("ChromaDB container failed to become healthy in time.")

        check_chromadb_ready()
        yield endpoint

@pytest.fixture(scope="function")
async def base_url(postgres_url: str) -> str:
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
        env: dict = os.environ.copy()
        cwd: str = project_root.path()

        api_process = subprocess.Popen(["uvicorn", "wizard.api:app"], cwd=cwd, env=env)

        while not health_check():  # 等待服务起来
            if api_process.poll() is not None:
                raise RuntimeError(f"api_process exit with code {api_process.returncode}")
            time.sleep(1)

        logger.debug({"base_url": base_url, "env": {"MBW_DB_URL": os.getenv("MBW_DB_URL")}})
        yield base_url

        api_process.terminate()
        api_process.wait()
    else:
        raise RuntimeError("Server already exists")


@pytest.fixture(scope="function")
async def worker_init(postgres_url: str) -> bool:
    env: dict = os.environ.copy()
    cwd: str = project_root.path()
    worker_process = subprocess.Popen(["python3", "main.py", "--workers", "1"], cwd=cwd, env=env)
    if worker_process.poll() is not None:
        raise RuntimeError(f"worker_process exit with code {worker_process.returncode}")
    yield True
    worker_process.terminate()
    worker_process.wait()

@pytest.fixture(scope="function")
def config(postgres_url: str, chromadb_endpoint: str) -> Config:
    load_dotenv()

    os.environ[f"{ENV_PREFIX}_DB_URL"] = postgres_url
    os.environ[f"{ENV_PREFIX}_VECTOR_HOST"], os.environ[f"{ENV_PREFIX}_VECTOR_PORT"] = chromadb_endpoint.split(":")

    loader = Loader(Config, env_prefix=ENV_PREFIX)
    config = loader.load()
    yield config

@pytest.fixture(scope="function")
def client(config: Config) -> str:
    with TestClient(app) as client:
        yield client
