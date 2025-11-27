import asyncio
from functools import partial

import httpx
from opentelemetry import trace
from pydantic import BaseModel

from common.trace_info import TraceInfo
from omnibox_wizard.wizard.config import OpenAIConfig, RerankerConfig
from omnibox_wizard.wizard.grimoire.entity.retrieval import BaseRetrieval
from omnibox_wizard.wizard.grimoire.entity.tools import ToolExecutorConfig
from omnibox_wizard.wizard.grimoire.retriever.base import SearchFunction, BaseRetriever

tracer = trace.get_tracer(__name__)


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
        self.config: OpenAIConfig | None = config.openai
        self.k: int | None = config.k
        self.threshold: float | None = config.threshold

    @tracer.start_as_current_span("Reranker.rerank")
    async def rerank(
        self,
        query: str,
        retrievals: list[BaseRetrieval],
        k: int | None = None,
        threshold: float | None = None,
        trace_info: TraceInfo | None = None,
    ) -> list[BaseRetrieval]:
        unique_retrievals = []
        for retrieval in retrievals:
            if retrieval not in unique_retrievals:
                unique_retrievals.append(retrieval)
        if not unique_retrievals:
            return []
        if not self.config:
            return unique_retrievals

        k = k or self.k
        threshold = threshold or self.threshold
        async with httpx.AsyncClient(
            base_url=self.config.base_url, timeout=300
        ) as client:
            response = await client.post(
                "/rerank",
                json={
                    "model": self.config.model,
                    "query": query,
                    "documents": [
                        retrieval.to_prompt(exclude_id=True)
                        for retrieval in unique_retrievals
                    ],
                    "top_n": k or len(unique_retrievals),
                    "return_documents": False,
                },
                headers={"Authorization": f"Bearer {self.config.api_key}"},
            )
            response.raise_for_status()
            rerank_response: RerankResponse = RerankResponse.model_validate(
                response.json()
            )
        reranked_results: list[BaseRetrieval] = []
        for item in rerank_response.results:
            retrieval: BaseRetrieval = unique_retrievals[item.index]
            retrieval.score.rerank = item.relevance_score
            reranked_results.append(retrieval)
        filtered_results: list[BaseRetrieval] = reranked_results
        if threshold is not None:
            filtered_results = [
                result
                for result in reranked_results
                if result.score.rerank >= threshold
            ]
        if trace_info:
            trace_info.debug(
                {
                    "query": query,
                    "k": k,
                    "threshold": threshold,
                    "rerank_response": rerank_response.model_dump(),
                    "len(retrievals)": len(retrievals),
                    "len(unique_retrievals)": len(unique_retrievals),
                    "len(reranked_results)": len(reranked_results),
                    "len(filtered_results)": len(filtered_results),
                }
            )
        return filtered_results[:k] if k else filtered_results

    def wrap(self, func: SearchFunction, *args, **kwargs) -> SearchFunction:
        async def wrapped(query: str) -> list[BaseRetrieval]:
            return await self.rerank(query, await func(query), *args, **kwargs)

        return wrapped

    @tracer.start_as_current_span("Reranker.search")
    async def search(
        self, query: str, funcs: list[SearchFunction], *args, **kwargs
    ) -> list[BaseRetrieval]:
        results = await asyncio.gather(*[func(query) for func in funcs])
        flattened_results: list[BaseRetrieval] = sum(results, [])
        reranked_results = await self.rerank(query, flattened_results, *args, **kwargs)
        return reranked_results


def get_merged_description(tools: list[dict]) -> str:
    descriptions = [f"- {tool['function']['description']}" for tool in tools]
    return "\n".join(
        [
            "This tool can search for various types of information, they include but are not limited to:",
            *descriptions,
        ]
    )


def get_tool_executor_config(
    tool_executor_config_list: list[ToolExecutorConfig],
    reranker: Reranker,
) -> ToolExecutorConfig:
    funcs = [config["func"] for config in tool_executor_config_list]
    name = "search"
    description: str = get_merged_description(
        [config["schema"] for config in tool_executor_config_list]
    )
    return ToolExecutorConfig(
        name=name,
        func=partial(reranker.search, funcs=funcs),
        schema=BaseRetriever.generate_schema(name, description),
    )
