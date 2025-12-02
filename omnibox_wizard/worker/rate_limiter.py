import asyncio

from omnibox_wizard.worker.config import RateLimiterConfig
from omnibox_wizard.worker.entity import Task


class RateLimiter:
    def __init__(self, config: RateLimiterConfig):
        self.config = config
        self.limits = {"file_reader": config.file_reader}
        self.semaphores: dict[str, asyncio.Semaphore] = {}

    def _get_semaphore(self, function: str) -> asyncio.Semaphore | None:
        limit = self.limits.get(function)
        if limit is None:
            return None
        if function not in self.semaphores:
            self.semaphores[function] = asyncio.Semaphore(limit)
        return self.semaphores[function]

    async def acquire(self, task: Task) -> None:
        semaphore = self._get_semaphore(task.function)
        if semaphore is None:
            return
        await semaphore.acquire()

    def release(self, task: Task) -> None:
        semaphore = self._get_semaphore(task.function)
        if semaphore is None:
            return
        semaphore.release()
