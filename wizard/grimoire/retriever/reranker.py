import asyncio
from typing import Callable, Awaitable

import httpx
from pydantic import BaseModel

from wizard.config import OpenAIConfig
from wizard.grimoire.entity.retrieval import BaseRetrieval

BaseRetriever = Callable[[str], Awaitable[list[BaseRetrieval]]]


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
    def __init__(self, funcs: list[BaseRetriever], config: OpenAIConfig | None):
        self.funcs: list[BaseRetriever] = funcs
        self.config: OpenAIConfig | None = config

    async def search(self, query: str) -> list[BaseRetrieval]:
        results = await asyncio.gather(*[func(query) for func in self.funcs])
        flattened_results: list[BaseRetrieval] = sum(results, [])
        if not self.config or not flattened_results:
            return flattened_results
        async with httpx.AsyncClient(base_url=self.config.base_url) as client:
            response = await client.post(
                "/rerank",
                json={
                    "model": self.config.model,
                    "query": query,
                    "documents": [result.to_prompt() for result in flattened_results],
                    "top_n": 20,
                    "return_documents": False
                },
                headers={"Authorization": f"Bearer {self.config.api_key}"}
            )
            response.raise_for_status()
            rerank_response: RerankResponse = RerankResponse.model_validate(response.json())
        reranked_results: list[BaseRetrieval] = []
        for item in rerank_response.results:
            if item.relevance_score > 0.5:
                retrieval: BaseRetrieval = flattened_results[item.index]
                retrieval.score.rerank = item.relevance_score
                reranked_results.append(retrieval)
        return reranked_results
