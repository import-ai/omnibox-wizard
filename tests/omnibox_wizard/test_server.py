import asyncio
import os
from concurrent.futures import ThreadPoolExecutor

from uvicorn import Config, Server

from omnibox_wizard.wizard.api.server import app
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.worker import Worker


def run_server_in_thread(host: str, port: int):
    config = Config(app=app, host=host, port=port, reload=True)
    server = Server(config)
    server.run()


async def start_server(config: Config, worker_config: WorkerConfig):
    loop = asyncio.get_event_loop()
    with ThreadPoolExecutor() as executor:
        server_future = loop.run_in_executor(
            executor,
            run_server_in_thread,
            "127.0.0.1",
            int(os.environ.get("PORT", "8001")),
        )
        await asyncio.sleep(3)
        worker = Worker(config=worker_config, worker_id=0)
        task = asyncio.create_task(worker.run())
        await server_future
    await task


async def test_server(config: Config, worker_config: WorkerConfig):
    await start_server(config, worker_config)


async def test_server_with_remote_db(
    remote_config: Config, remote_worker_config: WorkerConfig
):
    await start_server(remote_config, remote_worker_config)
