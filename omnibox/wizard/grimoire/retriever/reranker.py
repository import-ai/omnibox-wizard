import asyncio
from functools import partial

import httpx
from pydantic import BaseModel

from omnibox.common.trace_info import TraceInfo
from omnibox.wizard.config import OpenAIConfig, RerankerConfig
from omnibox.wizard.grimoire.entity.retrieval import BaseRetrieval
from omnibox.wizard.grimoire.entity.tools import ToolExecutorConfig
from omnibox.wizard.grimoire.retriever.base import SearchFunction, BaseRetriever


class BilledUnits(BaseModel):
    input_tokens: int
    output_tokens: int
    search_units: int
    classifications: int


class Tokens(BaseModel):
    input_tokens: int
    output_tokens: int


class Meta(BaseModel):
    billed_units: BilledUnits
    tokens: Tokens


class ResultItem(BaseModel):
    index: int
    relevance_score: float


class RerankResponse(BaseModel):
    id: str
    results: list[ResultItem]
    meta: Meta


class Reranker:
    def __init__(self, config: RerankerConfig):
        self.config: OpenAIConfig = config.openai
        self.k: int | None = config.k
        self.threshold: float | None = config.threshold

    async def rerank(
            self,
            query: str,
            retrievals: list[BaseRetrieval],
            k: int | None = None,
            threshold: float | None = None,
            trace_info: TraceInfo | None = None,
    ) -> list[BaseRetrieval]:
        if not retrievals:
            return []

        k = k or self.k
        threshold = threshold or self.threshold
        async with httpx.AsyncClient(base_url=self.config.base_url) as client:
            response = await client.post(
                "/rerank",
                json={
                    "model": self.config.model,
                    "query": query,
                    "documents": [retrieval.to_prompt() for retrieval in retrievals],
                    "top_n": k or len(retrievals),
                    "return_documents": False
                },
                headers={"Authorization": f"Bearer {self.config.api_key}"}
            )
            response.raise_for_status()
            rerank_response: RerankResponse = RerankResponse.model_validate(response.json())
        reranked_results: list[BaseRetrieval] = []
        for item in rerank_response.results:
            if threshold is None or item.relevance_score > threshold:
                retrieval: BaseRetrieval = retrievals[item.index]
                retrieval.score.rerank = item.relevance_score
                reranked_results.append(retrieval)
        if trace_info:
            trace_info.debug({
                "query": query,
                "k": k,
                "threshold": threshold,
                "rerank_response": rerank_response.model_dump(),
                "len(retrievals)": len(retrievals),
                "len(rerank_response.results)": len(rerank_response.results),
                "len(reranked_results)": len(reranked_results),
            })
        return reranked_results[:k] if k else reranked_results

    def wrap(self, func: SearchFunction, *args, **kwargs) -> SearchFunction:
        async def wrapped(query: str) -> list[BaseRetrieval]:
            return await self.rerank(query, await func(query), *args, **kwargs)

        return wrapped

    async def search(self, query: str, funcs: list[SearchFunction], *args, **kwargs) -> list[BaseRetrieval]:
        results = await asyncio.gather(*[func(query) for func in funcs])
        flattened_results: list[BaseRetrieval] = sum(results, [])
        reranked_results = await self.rerank(query, flattened_results, *args, **kwargs)
        return reranked_results


def get_merged_description(tools: list[dict]) -> str:
    descriptions = [f'- {tool["function"]["description"]}' for tool in tools]
    return '\n'.join([
        "This tool can search for various types of information, they include but are not limited to:",
        *descriptions
    ])


def get_tool_executor_config(
        tool_executor_config_list: list[ToolExecutorConfig],
        reranker: Reranker | None = None,
) -> ToolExecutorConfig:
    funcs = [config["func"] for config in tool_executor_config_list]
    name = "search"
    description: str = get_merged_description([config["schema"] for config in tool_executor_config_list])
    return ToolExecutorConfig(
        name=name,
        func=partial(reranker.search, funcs=funcs),
        schema=BaseRetriever.generate_schema(name, description)
    )
