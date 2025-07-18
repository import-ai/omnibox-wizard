import asyncio
from datetime import datetime
from functools import partial
from typing import Literal

import httpx

from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.wizard.grimoire.entity.retrieval import Citation, BaseRetrieval
from omnibox_wizard.wizard.grimoire.entity.tools import BaseTool
from omnibox_wizard.wizard.grimoire.retriever.base import BaseRetriever, SearchFunction


class SearXNGRetrieval(BaseRetrieval):
    result: dict
    source: Literal["web"] = "web"

    def to_prompt(self, i: int | None = None) -> str:
        citation = self.to_citation()
        return citation.to_prompt(i)

    def to_citation(self) -> Citation:
        citation: Citation = Citation(
            link=self.result['url'],
            title=self.result['title'],
            snippet=self.result['content'],
            updated_at=format_date(self.result.get('publishedDate', None)),
            source=self.source,
        )
        return citation


def format_date(date: str | None) -> str | None:
    if date:
        return datetime.fromisoformat(date).strftime("%Y-%m-%d %H:%M:%S")
    return None


class SearXNG(BaseRetriever):
    def __init__(self, base_url: str, engines: str | None = None):
        self.base_url: str = base_url
        self.engines: str | None = engines

    async def search(
            self,
            query: str,
            *,
            page_number: int = 1,
            k: int | None = None,
            retry_cnt: int = 2,  # First time may fail due to cold start, retry a few times
            retry_sleep: float = 1,
            trace_info: TraceInfo | None = None,
    ) -> list[SearXNGRetrieval]:
        for i in range(retry_cnt + 1):
            async with httpx.AsyncClient(base_url=self.base_url) as c:
                httpx_response: httpx.Response = await c.get(
                    "/search", params={"q": query, "pageno": page_number, "format": "json"} | (
                        {"engines": self.engines} if self.engines else {}
                    )
                )
                httpx_response.raise_for_status()
            search_result: dict = httpx_response.json()
            results: list[dict] = search_result['results']
            retrievals: list[SearXNGRetrieval] = [SearXNGRetrieval(result=result) for result in results]
            if trace_info:
                trace_info.debug({"len(retrievals)": len(retrievals)})
            if retrievals:
                return retrievals[:k] if k else retrievals
            if trace_info:
                trace_info.warning({
                    "message": f"Search failed, retrying {i + 1}/{retry_cnt + 1}",
                    "query": query,
                    "page_number": page_number,
                    "k": k
                })
            await asyncio.sleep(retry_sleep)
        return []

    def get_function(self, tool: BaseTool, **kwargs) -> SearchFunction:
        return partial(self.search, **kwargs)

    @classmethod
    def get_schema(cls) -> dict:
        return cls.generate_schema(
            "web_search",
            "Search the web for public information. Return in <cite id=\"\"></cite> format."
        )
