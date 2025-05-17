from datetime import datetime

import httpx

from common.trace_info import TraceInfo
from wizard.grimoire.entity.retrieval import Citation, BaseRetrieval


class SearXNGRetrieval(BaseRetrieval):
    result: dict

    def to_prompt(self) -> str:
        citation = self.to_citation()
        return "\n".join([
            f"Title: {citation.title}",
            f"Snippet:",
            citation.snippet,
            f"Updated at: {citation.updated_at}"
        ])

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


class SearXNG:
    def __init__(self, base_url: str):
        self.base_url: str = base_url

    async def search(
            self,
            query: str,
            page_number: int = 1,
            trace_info: TraceInfo | None = None
    ) -> list[SearXNGRetrieval]:
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
        return retrievals
