import asyncio
import tomllib

from common import project_root
from common.config_loader import Loader
from common.logger import get_logger
from common.tracing import setup_opentelemetry
from omnibox_wizard.worker.config import ENV_PREFIX, WorkerConfig
from omnibox_wizard.worker.health_server import HealthServer
from omnibox_wizard.worker.health_tracker import HealthTracker
from omnibox_wizard.worker.worker import Worker, compute_supported_functions

with project_root.open("pyproject.toml", "rb") as f:
    version = tomllib.load(f)["project"]["version"]

# Functions that operate on the vector index (see worker/functions/index.py).
INDEX_FUNCTIONS: frozenset[str] = frozenset(
    {
        "upsert_index",
        "delete_index",
        "upsert_message_index",
        "delete_conversation",
    }
)


async def run_worker(
    config: WorkerConfig,
    id: int,
    functions: list[str],
    health_tracker: HealthTracker,
):
    logger = get_logger(f"worker-{id}")
    worker = Worker(config, id, functions, health_tracker)
    while True:
        try:
            # Poll the backend for the next task this worker can handle. When
            # there is nothing to do, wait a second before polling again.
            task = await worker.poll_task()
            if task is None:
                await asyncio.sleep(1)
                continue
            await worker.process_polled_task(task)
        except Exception:
            logger.exception(f"Worker {id} encountered an error")
            await asyncio.sleep(5)


async def main():
    setup_opentelemetry("omnibox-wizard-worker")

    logger = get_logger("main")

    loader = Loader(WorkerConfig, env_prefix=ENV_PREFIX)
    config = loader.load()

    # Split the supported functions into file_reader_* kinds, index related
    # functions and everything else, then spawn a dedicated pool of workers for
    # each group.
    supported = compute_supported_functions(config.task)
    file_reader_functions = [f for f in supported if f.startswith("file_reader_")]
    index_functions = [f for f in supported if f in INDEX_FUNCTIONS]
    other_functions = [
        f
        for f in supported
        if not f.startswith("file_reader_") and f not in INDEX_FUNCTIONS
    ]

    logger.info(
        f"Starting Wizard {version} with {config.file_reader_worker_num} file_reader "
        f"workers, {config.index_worker_num} index workers and "
        f"{config.other_worker_num} other workers"
    )

    health_tracker = HealthTracker()
    tasks = []
    worker_id = 0
    for num, functions in (
        (config.file_reader_worker_num, file_reader_functions),
        (config.index_worker_num, index_functions),
        (config.other_worker_num, other_functions),
    ):
        if not functions:
            continue
        for _ in range(num):
            tasks.append(run_worker(config, worker_id, functions, health_tracker))
            worker_id += 1

    # Add health server if enabled
    if config.health.enabled:
        health_server = HealthServer(health_tracker, config.health.port)
        logger.info(f"Starting health check server on port {config.health.port}")
        tasks.append(health_server.start())

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
