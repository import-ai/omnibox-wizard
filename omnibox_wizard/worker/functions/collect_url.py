from bs4 import BeautifulSoup

import httpx
from opentelemetry import trace
from pydantic import BaseModel

from common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task, TaskFunction
from omnibox_wizard.worker.functions.base_function import BaseFunction

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

    @tracer.start_as_current_span("CollectUrlFunction.run")
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        span = trace.get_current_span()
        input_dict = task.input
        url = input_dict["url"]
        span.set_attribute("url", url)
        scrape_result = await self._scrape_url(url)
        collect_task = task.create_next_task(
            TaskFunction.COLLECT,
            {
                "url": scrape_result.final_url,
                "html": scrape_result.html,
                "title": scrape_result.title,
            },
        )
        return {"next_tasks": [collect_task.model_dump()]}

    @tracer.start_as_current_span("CollectUrlFunction._scrape_url")
    async def _scrape_url(self, url: str) -> ScrapeResponseDto:
        if self.scrape_base_url:
            async with httpx.AsyncClient(
                base_url=self.scrape_base_url, timeout=self.timeout * 2 + 3
            ) as client:
                response = await client.post("/api/v1/scrape", json={"url": url})
                assert response.is_success, response.text
                json_response: dict = response.json()
            return ScrapeResponseDto.model_validate(json_response)
        return await scrape(url, self.timeout)
