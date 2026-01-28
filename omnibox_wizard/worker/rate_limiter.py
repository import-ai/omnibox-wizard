import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from omnibox_wizard.worker.config import RateLimiterConfig
from wizard_common.worker.entity import Message


class RateLimiter:
    def __init__(self, config: RateLimiterConfig):
        self.config = config
        self.semaphores: dict[str, asyncio.Semaphore] = {
            key: asyncio.Semaphore(value) for key, value in config.model_dump().items()
        }

    def _get_key(self, msg: Message) -> str | None:
        if msg.function == "file_reader":
            file_name = msg.meta.get("file_name", "")
            ext = Path(file_name).suffix.lower()
            if ext in [".pptx", ".docx", ".ppt", ".doc"]:
                return "file_reader_doc"
            elif ext in [".md"]:
                return "file_reader_md"
            elif ext in [".txt"]:
                return "file_reader_txt"
        return None

    def _get_semaphore(self, msg: Message) -> asyncio.Semaphore | None:
        key = self._get_key(msg)
        if key is None:
            return None
        return self.semaphores.get(key)

    async def acquire(self, msg: Message) -> None:
        semaphore = self._get_semaphore(msg)
        if semaphore is None:
            return
        await semaphore.acquire()

    def release(self, msg: Message) -> None:
        semaphore = self._get_semaphore(msg)
        if semaphore is None:
            return
        semaphore.release()

    @asynccontextmanager
    async def limit(self, msg: Message):
        await self.acquire(msg)
        try:
            yield
        finally:
            self.release(msg)
