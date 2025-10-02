import asyncio
import base64
import os
from abc import abstractmethod, ABC
from urllib.parse import urlparse

import httpx
from opentelemetry import trace

from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import GeneratedContent, Image

tracer = trace.get_tracer("HTMLReaderBaseProcessor")


class HTMLReaderBaseProcessor(ABC):

    def __init__(self, config: WorkerConfig):
        self.config = config

    @classmethod
    def get_name_from_url(cls, url: str) -> str:
        parsed = urlparse(url)
        filename = os.path.basename(parsed.path)
        return filename

    @classmethod
    @tracer.start_as_current_span("fetch_img")
    async def fetch_img(cls, url: str) -> tuple[str, str] | None:
        span = trace.get_current_span()
        span.set_attribute("url", url)
        if not url.startswith("http"):
            return None
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                httpx_response = await client.get(url)
                if httpx_response.is_success:
                    mimetype = httpx_response.headers.get("Content-Type", "image/jpeg")
                    base64_data = base64.b64encode(httpx_response.content).decode()
                    return mimetype, base64_data
        except Exception as e:
            span.record_exception(e)
        return None

    @classmethod
    async def get_images(cls, tuple_images: list[tuple[str, str]]) -> list[Image]:
        fetched_imgs = await asyncio.gather(*[cls.fetch_img(src) for src, _ in tuple_images])
        images: list[Image] = []

        for (src, alt), pair in zip(tuple_images, fetched_imgs):
            if pair:
                mimetype, base64_data = pair
                images.append(Image.model_validate({
                    "name": alt or HTMLReaderBaseProcessor.get_name_from_url(src),
                    "link": src,
                    "data": base64_data,
                    "mimetype": mimetype,
                }))
        return images

    @classmethod
    def get_domain(cls, url: str) -> str:
        return urlparse(url).netloc

    @abstractmethod
    def hit(self, html: str, url: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    async def convert(self, html: str, url: str) -> GeneratedContent:
        raise NotImplementedError
