import asyncio
import tomllib
from argparse import ArgumentParser, Namespace

from aiokafka import AIOKafkaConsumer

from common import project_root
from common.config_loader import Loader
from common.logger import get_logger
from common.tracing import setup_opentelemetry
from omnibox_wizard.worker.config import ENV_PREFIX, WorkerConfig
from omnibox_wizard.worker.entity import Message
from omnibox_wizard.worker.health_server import HealthServer
from omnibox_wizard.worker.health_tracker import HealthTracker
from omnibox_wizard.worker.rate_limiter import RateLimiter
from omnibox_wizard.worker.worker import Worker

with project_root.open("pyproject.toml", "rb") as f:
    version = tomllib.load(f)["project"]["version"]


def get_args() -> Namespace:
    parser = ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    return args


async def run_worker(
    config: WorkerConfig,
    id: int,
    health_tracker: HealthTracker,
    rate_limiter: RateLimiter,
):
    consumer = AIOKafkaConsumer(
        config.kafka.topic,
        bootstrap_servers=config.kafka.broker,
        group_id=config.kafka.group,
        enable_auto_commit=True,
    )
    await consumer.start()
    worker = Worker(config, id, health_tracker, rate_limiter)
    async for msg in consumer:
        message = Message.model_validate_json(msg.value)
        await worker.process_message(message)


async def main():
    setup_opentelemetry("omnibox-wizard-worker")

    args = get_args()
    logger = get_logger("main")
    logger.info(f"Starting Wizard {version} with {args.workers} workers")

    loader = Loader(WorkerConfig, env_prefix=ENV_PREFIX)
    config = loader.load()

    health_tracker = HealthTracker()
    rate_limiter = RateLimiter(config.rate)
    tasks = [
        run_worker(config, i, health_tracker, rate_limiter) for i in range(args.workers)
    ]

    # Add health server if enabled
    if config.health.enabled:
        health_server = HealthServer(health_tracker, config.health.port)
        logger.info(f"Starting health check server on port {config.health.port}")
        tasks.append(health_server.start())

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
