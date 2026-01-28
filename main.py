import asyncio
import tomllib
from argparse import ArgumentParser, Namespace

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import CommitFailedError, IllegalStateError

from common import project_root
from common.config_loader import Loader
from common.logger import get_logger
from common.tracing import setup_opentelemetry
from omnibox_wizard.worker.config import ENV_PREFIX, WorkerConfig
from wizard_common.worker.entity import Message
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
    logger = get_logger(f"worker-{id}")

    # Create consumers for each priority level (3 is highest, 1 is lowest)
    # Also include the original topic for backward compatibility (lowest priority)
    topics = [
        f"{config.kafka.topic}-3",
        f"{config.kafka.topic}-2",
        f"{config.kafka.topic}-1",
        config.kafka.topic,  # Original topic for backward compatibility
    ]
    consumers = []
    for topic in topics:
        consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=config.kafka.broker,
            group_id=config.kafka.group,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
        )
        await consumer.start()
        consumers.append(consumer)

    worker = Worker(config, id, health_tracker, rate_limiter)
    try:
        while True:
            processed_any = False
            for consumer in consumers:
                result = await consumer.getmany(timeout_ms=0, max_records=1)
                for tp, messages in result.items():
                    for msg in messages:
                        message = Message.model_validate_json(msg.value)
                        await worker.process_message(message)
                        processed_any = True
                        try:
                            await consumer.commit({tp: msg.offset + 1})
                        except CommitFailedError as e:
                            logger.warning(f"Commit failed: {e}")
                        except IllegalStateError as e:
                            logger.warning(f"Commit failed: {e}")
                if processed_any:
                    break
            if not processed_any:
                await asyncio.sleep(0.5)
    finally:
        for consumer in consumers:
            await consumer.stop()


async def run_worker_loop(
    config: WorkerConfig,
    id: int,
    health_tracker: HealthTracker,
    rate_limiter: RateLimiter,
):
    logger = get_logger(f"worker-{id}")
    while True:
        try:
            await run_worker(config, id, health_tracker, rate_limiter)
        except Exception:
            logger.exception(f"Worker {id} encountered an error")
        await asyncio.sleep(5)


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
        run_worker_loop(config, i, health_tracker, rate_limiter)
        for i in range(args.workers)
    ]

    # Add health server if enabled
    if config.health.enabled:
        health_server = HealthServer(health_tracker, config.health.port)
        logger.info(f"Starting health check server on port {config.health.port}")
        tasks.append(health_server.start())

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
