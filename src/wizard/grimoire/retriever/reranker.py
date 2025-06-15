import asyncio
from functools import partial

import httpx
from pydantic import BaseModel

from src.wizard.config import OpenAIConfig
from src.wizard.grimoire.entity.retrieval import BaseRetrieval
from src.wizard.grimoire.entity.tools import ToolExecutorConfig
from src.wizard.grimoire.retriever.base import SearchFunction, BaseRetriever


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


def get_merged_description(tools: list[dict]) -> str:
    descriptions = [f'- {tool["function"]["description"]}' for tool in tools]
    return '\n'.join([
        "This tool can search for various types of information, they include but are not limited to:",
        *descriptions
    ])


def get_tool_executor_config(
        tool_executor_config_list: list[ToolExecutorConfig],
        openai_config: OpenAIConfig | None
) -> ToolExecutorConfig:
    funcs = [config["func"] for config in tool_executor_config_list]
    name = "search"
    description: str = get_merged_description([config["schema"] for config in tool_executor_config_list])
    return ToolExecutorConfig(
        name=name,
        func=partial(Reranker(openai_config).search, funcs=funcs),
        schema=BaseRetriever.generate_schema(name, description)
    )


class Reranker:
    def __init__(self, config: OpenAIConfig):
        self.config: OpenAIConfig = config

    async def rerank(
            self,
            query: str,
            retrievals: list[BaseRetrieval],
            k: int | None = None,
            threshold: float | None = None
    ) -> list[BaseRetrieval]:
        if not retrievals:
            return []
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
        return reranked_results

    async def search(self, query: str, funcs: list[SearchFunction]) -> list[BaseRetrieval]:
        results = await asyncio.gather(*[func(query) for func in funcs])
        flattened_results: list[BaseRetrieval] = sum(results, [])
        reranked_results = await self.rerank(query, flattened_results)
        return reranked_results
