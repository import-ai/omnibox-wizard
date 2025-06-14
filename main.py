import asyncio
import tomllib
from argparse import Namespace, ArgumentParser

from src.common import project_root
from src.common.config_loader import Loader
from src.common.logger import get_logger
from src.wizard.config import WorkerConfig, ENV_PREFIX
from src.wizard.grimoire.retriever.meili_vector_db import init_meili_vector_db
from src.wizard.wand.worker import Worker

with project_root.open("pyproject.toml", "rb") as f:
    version = tomllib.load(f)["project"]["version"]


def get_args() -> Namespace:
    parser = ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    return args


async def main():
    args = get_args()
    get_logger("main").info(f"Starting Wizard {version} with {args.workers} workers")
    loader = Loader(WorkerConfig, env_prefix=ENV_PREFIX)
    config = loader.load()
    await init_meili_vector_db(config.vector)
    workers = [Worker(config=config, worker_id=i) for i in range(args.workers)]
    await asyncio.gather(*(worker.run() for worker in workers))


if __name__ == "__main__":
    asyncio.run(main())
