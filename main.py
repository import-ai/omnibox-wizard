import asyncio
from argparse import Namespace, ArgumentParser

from wizard.wand.worker import Worker


def get_args() -> Namespace:
    parser = ArgumentParser()
    parser.add_argument("--workers", type=int, default=1)
    args = parser.parse_args()
    return args


async def main():
    args = get_args()
    workers = [Worker(worker_id=i) for i in range(args.workers)]
    await asyncio.gather(*(worker.run() for worker in workers))


if __name__ == "__main__":
    asyncio.run(main())
