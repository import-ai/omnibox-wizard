import asyncio
import tomllib
from argparse import Namespace, ArgumentParser

from omnibox_wizard.common import project_root
from omnibox_wizard.common.config_loader import Loader
from omnibox_wizard.common.logger import get_logger
from omnibox_wizard.worker.config import WorkerConfig, ENV_PREFIX
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
    get_logger("main").info(f"Starting Wizard {version} with {args.workers} workers")
    loader = Loader(WorkerConfig, env_prefix=ENV_PREFIX)
    config = loader.load()
    workers = [Worker(config=config, worker_id=i) for i in range(args.workers)]
    await asyncio.gather(*(worker.run() for worker in workers))


if __name__ == "__main__":
    asyncio.run(main())
