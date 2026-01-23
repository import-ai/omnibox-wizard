import asyncio
from typing import Any

import httpx
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.functions.base_function import BaseFunction

tracer = trace.get_tracer(__name__)


class CrawlServiceError(Exception):
    """Raised when crawl service returns an error"""

    def __init__(self, message: str, error_detail: str | None = None):
        self.message = message
        self.error_detail = error_detail
        super().__init__(self.message)


class CollectUrlFunction(BaseFunction):
    """
    Collects content from a URL using the crawl service.

    This function:
    1. Fetches title and HTML from the crawl service at 127.0.0.1:18000
    2. Creates a collect task via the task chain dispatch system

    Input:
        url (str): The URL to collect

    Output:
        title (str): The page title
        html (str): The HTML content
        final_url (str): The final URL after redirects
        next_tasks (list): Next tasks to dispatch (collect task)
    """

    CRAWL_SERVICE_BASE_URL = "http://127.0.0.1:18000"
    CRAWL_TIMEOUT = 60  # seconds

    def __init__(self, config: WorkerConfig):
        self.config = config

    @tracer.start_as_current_span("CollectUrlFunction.run")
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        input_dict = task.input
        url = input_dict.get("url")

        if not url:
            trace_info.bind(error="missing_url").error({"error": "missing url"})
            raise ValueError("url is required in task input")

        span = trace.get_current_span()
        span.set_attribute("collect_url.url", url)

        trace_info = trace_info.bind(url=url)
        trace_info.info({"message": "fetching_url"})

        try:
            scrape_result = await self._scrape_url(url, trace_info)
        except CrawlServiceError as e:
            trace_info.bind(error=e.message).error(
                {"error": e.message, "detail": e.error_detail}
            )
            span.set_status(Status(StatusCode.ERROR, e.message))
            raise
        except Exception as e:
            error_msg = f"Failed to scrape URL: {str(e)}"
            trace_info.bind(error=error_msg).exception({"error": error_msg})
            span.set_status(Status(StatusCode.ERROR, error_msg))
            raise

        # Create the collect task as a next task
        collect_task = task.create_next_task(
            function="collect",
            input={
                "url": scrape_result["final_url"],
                "html": scrape_result["html"],
                "title": scrape_result["title"],
            },
        )

        result = {
            "title": scrape_result["title"],
            "html": scrape_result["html"],
            "final_url": scrape_result["final_url"],
            "status_code": scrape_result["status_code"],
            "next_tasks": [collect_task.model_dump()],
        }

        trace_info.info(
            {
                "message": "scraped_successfully",
                "title": scrape_result["title"],
                "final_url": scrape_result["final_url"],
                "html_length": len(scrape_result["html"]),
            }
        )

        return result

    @tracer.start_as_current_span("CollectUrlFunction._scrape_url")
    async def _scrape_url(self, url: str, trace_info: TraceInfo) -> dict[str, Any]:
        """
        Scrape the URL using the crawl service.

        Args:
            url: The URL to scrape

        Returns:
            A dict containing: html, title, final_url, status_code

        Raises:
            CrawlServiceError: If the crawl service returns an error
        """
        span = trace.get_current_span()

        async with httpx.AsyncClient(timeout=self.CRAWL_TIMEOUT) as client:
            response = await client.post(
                f"{self.CRAWL_SERVICE_BASE_URL}/api/v1/scrape",
                json={"url": url, "block_media": True},
            )
            response.raise_for_status()
            data = response.json()

        span.set_attributes(
            {
                "crawl_service.status_code": data.get("status_code"),
                "crawl_service.final_url": data.get("final_url", url),
                "crawl_service.has_html": bool(data.get("html")),
            }
        )

        # Check for crawl service errors
        if data.get("error"):
            raise CrawlServiceError(
                message=f"Crawl service error: {data['error']}",
                error_detail=data.get("error"),
            )

        # Validate required fields
        if not data.get("html"):
            raise CrawlServiceError(
                message="No HTML content returned from crawl service",
                error_detail=data.get("policy"),
            )

        return {
            "html": data["html"],
            "title": data.get("title") or "",
            "final_url": data.get("final_url") or url,
            "status_code": data.get("status_code"),
        }
