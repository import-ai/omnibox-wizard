import os
import subprocess
import time

import httpx
import pytest
from dotenv import load_dotenv
from fastapi.testclient import TestClient
from tests.helper.chroma_container import ChromaContainer

from common import project_root
from common.config_loader import Loader
from common.logger import get_logger
from common.trace_info import TraceInfo
from wizard.api.server import app
from wizard.config import Config, ENV_PREFIX
from wizard.wand.worker import Worker

logger = get_logger("fixture")


@pytest.fixture(scope="function")
def chromadb_endpoint() -> str:
    with ChromaContainer(image="chromadb/chroma:1.0.7") as chromadb:
        server_info: dict = chromadb.get_config()
        endpoint: str = server_info["endpoint"]
        os.environ[f"{ENV_PREFIX}_VECTOR_HOST"] = server_info["host"]
        os.environ[f"{ENV_PREFIX}_VECTOR_PORT"] = server_info["port"]

        def check_chromadb_ready() -> bool:
            for i in range(10):
                try:
                    with httpx.Client(base_url=f"http://{endpoint}", timeout=3) as client:  # noqa
                        response: httpx.Response = client.get("/api/v2/healthcheck")
                    response.raise_for_status()
                    return True
                except httpx.ConnectError:
                    time.sleep(1)
            raise RuntimeError("ChromaDB container failed to become healthy in time.")

        check_chromadb_ready()
        yield endpoint


@pytest.fixture(scope="function")
async def base_url() -> str:
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

        logger.debug({"base_url": base_url, "env": {"OBW_DB_URL": os.getenv("OBW_DB_URL")}})
        yield base_url

        api_process.terminate()
        api_process.wait()
    else:
        raise RuntimeError("Server already exists")


@pytest.fixture(scope="function")
def config(chromadb_endpoint: str) -> Config:
    load_dotenv()

    os.environ[f"{ENV_PREFIX}_VECTOR_HOST"], os.environ[f"{ENV_PREFIX}_VECTOR_PORT"] = chromadb_endpoint.split(":")

    loader = Loader(Config, env_prefix=ENV_PREFIX)
    config = loader.load()
    yield config


@pytest.fixture(scope="function")
def remote_config() -> Config:
    load_dotenv()

    os.environ[f"{ENV_PREFIX}_VECTOR_HOST"], os.environ[f"{ENV_PREFIX}_VECTOR_PORT"] = "chromadb:8001".split(":")

    loader = Loader(Config, env_prefix=ENV_PREFIX)
    config = loader.load()
    yield config


@pytest.fixture(scope="function")
def remote_client(remote_config: Config) -> httpx.Client:
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="function")
async def worker_init(config: Config) -> bool:
    env: dict = os.environ.copy()
    cwd: str = project_root.path()
    worker_process = subprocess.Popen(["python3", "main.py", "--workers", "1"], cwd=cwd, env=env)
    if worker_process.poll() is not None:
        raise RuntimeError(f"worker_process exit with code {worker_process.returncode}")
    yield True
    worker_process.terminate()
    worker_process.wait()


@pytest.fixture(scope="function")
def client(config: Config) -> httpx.Client:
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="function")
async def worker(config) -> Worker:
    worker = Worker(config=config, worker_id=0)
    await worker.async_init()
    return worker


@pytest.fixture(scope="function")
def trace_info() -> TraceInfo:
    return TraceInfo(logger=get_logger("test"))
