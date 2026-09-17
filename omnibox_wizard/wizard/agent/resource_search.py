from functools import partial

from opentelemetry import trace

from common.trace_info import TraceInfo
from omnibox_wizard.wizard.agent.backend_visible_client import BackendVisibleBaseClient
from wizard_common.grimoire.entity.chunk import ResourceChunkRetrieval
from wizard_common.grimoire.entity.tools import PrivateSearchTool
from wizard_common.grimoire.retriever.base import SearchFunction
from wizard_common.grimoire.retriever.weaviate_vector_db import WeaviateVectorRetriever

tracer = trace.get_tracer(__name__)


class ResourceSearch(WeaviateVectorRetriever):
    RESULT_LIMIT = 40
    EMPTY_OVERSAMPLE = 120
    SCOPED_OVERSAMPLE = 80

    @tracer.start_as_current_span("ResourceSearch.query")
    async def query(
        self,
        query: str,
        k: int = RESULT_LIMIT,
        *,
        private_search_tool: PrivateSearchTool,
        backend_client: BackendVisibleBaseClient | None = None,
        trace_info: TraceInfo | None = None,
    ) -> list[ResourceChunkRetrieval]:
        if private_search_tool.visible_resources is None:
            raise AssertionError(
                "`visible_resources` must be provided when searching resources."
            )
        oversample_k = (
            self.EMPTY_OVERSAMPLE
            if len(private_search_tool.visible_resources) == 0
            else self.SCOPED_OVERSAMPLE
        )
        span = trace.get_current_span()
        span.set_attributes(
            {
                "resource_search.k": k,
                "resource_search.oversample_k": oversample_k,
                "len(visible_resources)": len(private_search_tool.visible_resources),
            }
        )
        retrievals = await super().query(
            query,
            oversample_k,
            private_search_tool=private_search_tool,
            trace_info=trace_info,
        )
        if not retrievals:
            return []
        if backend_client is None:
            return []
        resource_ids = list(
            dict.fromkeys(retrieval.chunk.resource_id for retrieval in retrievals)
        )
        try:
            visible_ids = set(
                await backend_client.filter_visible_resource_ids(resource_ids)
            )
        except Exception as e:
            span.record_exception(e)
            return []
        return [
            retrieval
            for retrieval in retrievals
            if retrieval.chunk.resource_id in visible_ids
        ][:k]

    def get_function(
        self, private_search_tool: PrivateSearchTool, **kwargs
    ) -> SearchFunction:
        return partial(
            self.query,
            private_search_tool=private_search_tool,
            k=self.RESULT_LIMIT,
            **kwargs,
        )
