import asyncio
import tomllib
from argparse import ArgumentParser, Namespace
from typing import Set

from aiokafka import AIOKafkaConsumer, ConsumerRecord, TopicPartition

from common import project_root
from common.config_loader import Loader
from common.logger import get_logger
from common.tracing import setup_opentelemetry
from omnibox_wizard.worker.config import ENV_PREFIX, WorkerConfig
from omnibox_wizard.worker.health_server import HealthServer
from omnibox_wizard.worker.health_tracker import HealthTracker

with project_root.open("pyproject.toml", "rb") as f:
    version = tomllib.load(f)["project"]["version"]


def get_args() -> Namespace:
    parser = ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    return args


async def process(msg: ConsumerRecord):
    pass


class MessageConsumer:
    def __init__(self, topic: str, group_id: str, concurrency: int):
        self.consumer = AIOKafkaConsumer(
            topic, group_id=group_id, enable_auto_commit=False
        )
        self.concurrency = concurrency
        self.queue: asyncio.Queue[ConsumerRecord] = asyncio.Queue(maxsize=concurrency)
        self.processing_messages: Set[tuple[str, int, int]] = set()

    def get_smallest_offset(self, topic: str, partition: int) -> int:
        return min(
            (
                offset
                for t, p, offset in self.processing_messages
                if t == topic and p == partition
            ),
            default=0,
        )

    async def receive_messages(self):
        while True:
            msg = await self.consumer.getone()
            await self.queue.put(msg)

    async def worker(self):
        while True:
            msg = await self.queue.get()
            msg_info = (msg.topic, msg.partition, msg.offset)
            self.processing_messages.add(msg_info)

            await process(msg)

            offset = self.get_smallest_offset(msg.topic, msg.partition)
            tp = TopicPartition(msg.topic, msg.partition)
            await self.consumer.commit({tp: offset + 1})
            self.processing_messages.discard(msg_info)

    async def run(self):
        await self.consumer.start()
        tasks = [
            asyncio.create_task(self.receive_messages()),
            *[asyncio.create_task(self.worker()) for _ in range(self.concurrency)],
        ]
        await asyncio.gather(*tasks)


async def main():
    setup_opentelemetry("omnibox-wizard-worker")

    args = get_args()
    logger = get_logger("main")
    logger.info(f"Starting Wizard {version} with {args.workers} workers")

    loader = Loader(WorkerConfig, env_prefix=ENV_PREFIX)
    config = loader.load()

    # Initialize health tracking
    health_tracker = HealthTracker()

    message_consumer = MessageConsumer(
        topic=config.consumer.topic,
        group_id=config.consumer.group,
        concurrency=config.consumer.concurrency,
    )
    tasks = [message_consumer.run()]

    # Add health server if enabled
    if config.health.enabled:
        health_server = HealthServer(health_tracker, config.health.port)
        logger.info(f"Starting health check server on port {config.health.port}")
        tasks.append(health_server.start())

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
