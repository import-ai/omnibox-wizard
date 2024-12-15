import asyncio

from wizard.worker import Worker


async def main():
    # Number of workers you want to run concurrently
    num_workers = 4
    workers = [Worker(worker_id=i) for i in range(num_workers)]

    await asyncio.gather(*(worker.run() for worker in workers))


if __name__ == "__main__":
    asyncio.run(main())
