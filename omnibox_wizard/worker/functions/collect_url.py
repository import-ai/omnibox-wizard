import os

import httpx
from bs4 import BeautifulSoup
from opentelemetry import trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from pydantic import BaseModel

from common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.functions.base_function import BaseFunction
from wizard_common.worker.entity import Task, TaskFunction

tracer = trace.get_tracer(__name__)


class ScrapeResponseDto(BaseModel):
    final_url: str
    html: str
    title: str


@tracer.start_as_current_span("local.scrape")
async def scrape(url: str, timeout: int) -> ScrapeResponseDto:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        httpx_response: httpx.Response = await client.get(url)
        httpx_response.raise_for_status()
        html: str = httpx_response.text
        final_url: str = str(httpx_response.url)

    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    title: str = title_tag.get_text(strip=True) if title_tag else ""

    return ScrapeResponseDto(html=html, title=title, final_url=final_url)


class CollectUrlFunction(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.scrape_base_url: str | None = config.task.scrape_base_url
        self.timeout: int = 60
        self.video_prefixes: list[str] = list(
            filter(bool, os.getenv("OB_VIDEO_PREFIXES", "").split(","))
        )

    @staticmethod
    def _is_xiaohongshu_url(url: str) -> bool:
        if not url:
            return False
        return (
            "xiaohongshu.com" in url
            or "xhslink.com" in url
        )

    def _is_video_by_url(self, url: str) -> bool:
        for prefix in self.video_prefixes:
            if url.startswith(prefix):
                return True
        return False

    def _is_video_by_html(self, url: str, html: str) -> bool:
        if not html:
            return False
        try:
            soup = BeautifulSoup(html, "html.parser")
            if soup.find("video"):
                return True
            meta_type = soup.find("meta", property="og:type")
            if meta_type and meta_type.get("content") == "video":
                return True
            if self._is_xiaohongshu_url(url) and '"type":"video"' in html:
                return True
        except Exception:
            return False
        return False

    def is_video(self, url: str, html: str) -> bool:
        if self._is_video_by_url(url):
            return True
        if self._is_video_by_html(url, html):
            return True
        return False

    @tracer.start_as_current_span("CollectUrlFunction.run")
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        span = trace.get_current_span()
        input_dict = task.input
        url = input_dict["url"]
        span.set_attribute("url", url)
        scrape_result = await self._scrape_url(url)
        is_video = self.is_video(scrape_result.final_url, scrape_result.html)
        span.set_attribute("is_video", is_video)
        return {
            "next_tasks": [
                task.create_next_task(
                    TaskFunction.GENERATE_VIDEO_NOTE
                    if is_video
                    else TaskFunction.COLLECT,
                    {
                        "url": scrape_result.final_url,
                        "html": scrape_result.html,
                        "title": scrape_result.title,
                    },
                ).model_dump()
            ]
        }

    @tracer.start_as_current_span("CollectUrlFunction._scrape_url")
    async def _scrape_url(self, url: str) -> ScrapeResponseDto:
        if self.scrape_base_url:
            async with httpx.AsyncClient(
                base_url=self.scrape_base_url, timeout=self.timeout * 2 + 3
            ) as client:
                HTTPXClientInstrumentor.instrument_client(client)
                response = await client.post("/api/v1/scrape", json={"url": url})
                assert response.is_success, response.text
                json_response: dict = response.json()
            return ScrapeResponseDto.model_validate(json_response)
        return await scrape(url, self.timeout)
