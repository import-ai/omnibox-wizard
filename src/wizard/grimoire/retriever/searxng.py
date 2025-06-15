import asyncio
from datetime import datetime
from functools import partial
from urllib.parse import urlparse

import httpx

from src.common.trace_info import TraceInfo
from src.common.utils import remove_continuous_break_lines
from src.wizard.grimoire.entity.retrieval import Citation, BaseRetrieval
from src.wizard.grimoire.entity.tools import BaseTool
from src.wizard.grimoire.retriever.base import BaseRetriever, SearchFunction


def get_domain(url: str) -> str:
    return urlparse(url).netloc


class SearXNGRetrieval(BaseRetrieval):
    result: dict

    def source(self) -> str:
        return "web"

    def to_prompt(self) -> str:
        citation = self.to_citation()
        contents: list[str] = []

        if citation.title:
            contents.append(f"<title>{citation.title}</title>")
        if citation.snippet:
            contents.append(f"<snippet>{citation.snippet}</snippet>")
        if citation.updated_at:
            contents.append(f"<updated_at>{citation.updated_at}</updated_at>")
        if citation.link and (host := get_domain(citation.link)):
            contents.append(f"<host>{host}</host>")

        return remove_continuous_break_lines("\n".join(contents))

    def to_citation(self) -> Citation:
        citation: Citation = Citation(
            link=self.result['url'],
            title=self.result['title'],
            snippet=self.result['content'],
            updated_at=format_date(self.result.get('publishedDate', None))
        )
        return citation


def format_date(date: str | None) -> str | None:
    if date:
        return datetime.fromisoformat(date).strftime("%Y-%m-%d %H:%M:%S")
    return None


class SearXNG(BaseRetriever):
    def __init__(self, base_url: str):
        self.base_url: str = base_url

    async def search(
            self,
            query: str,
            *,
            page_number: int = 1,
            k: int = 20,
            retry_cnt: int = 2,  # First time may fail due to cold start, retry a few times
            retry_sleep: float = 1,
            trace_info: TraceInfo | None = None
    ) -> list[SearXNGRetrieval]:
        for i in range(retry_cnt + 1):
            async with httpx.AsyncClient(base_url=self.base_url) as c:
                httpx_response: httpx.Response = await c.get(
                    "/search", params={"q": query, "pageno": page_number, "format": "json"}
                )
                httpx_response.raise_for_status()
            search_result: dict = httpx_response.json()
            results: list[dict] = search_result['results']
            retrievals: list[SearXNGRetrieval] = [SearXNGRetrieval(result=result) for result in results]
            if trace_info:
                trace_info.debug({"len(retrievals)": len(retrievals)})
            if retrievals:
                return retrievals[:k]
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
        return cls.generate_schema("web_search", "Search the web for public information.")
