import asyncio
import tomllib
from argparse import Namespace, ArgumentParser

from omnibox_wizard.common import project_root
from omnibox_wizard.common.config_loader import Loader
from omnibox_wizard.common.logger import get_logger
from omnibox_wizard.worker.config import WorkerConfig, ENV_PREFIX
from omnibox_wizard.worker.health_server import HealthServer
from omnibox_wizard.worker.health_tracker import HealthTracker
from omnibox_wizard.worker.worker import Worker

with project_root.open("pyproject.toml", "rb") as f:
    version = tomllib.load(f)["project"]["version"]


def get_args() -> Namespace:
    parser = ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    return args


async def main():
    args = get_args()
    logger = get_logger("main")
    logger.info(f"Starting Wizard {version} with {args.workers} workers")

    loader = Loader(WorkerConfig, env_prefix=ENV_PREFIX)
    config = loader.load()

    # Initialize health tracking
    health_tracker = HealthTracker()
    workers = [Worker(config=config, worker_id=i, health_tracker=health_tracker) for i in range(args.workers)]

    # Create tasks list
    tasks = [worker.run() for worker in workers]

    # Add health server if enabled
    if config.health.enabled:
        health_server = HealthServer(health_tracker, config.health.port)
        logger.info(f"Starting health check server on port {config.health.port}")
        tasks.append(health_server.start())

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
