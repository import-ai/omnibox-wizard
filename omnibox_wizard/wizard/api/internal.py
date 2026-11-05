from functools import partial
from json import dumps as lib_dumps

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from common.config_loader import Loader
from common.trace_info import TraceInfo
from omnibox_wizard.indexing import build_resource_chunks
from omnibox_wizard.wizard.api.depends import get_trace_info
from omnibox_wizard.wizard.api.entity import (
    CommonAITextRequest,
    RssItemParseRequest,
    RssItemParseResponse,
    SearchRequest,
    SearchResponse,
    TitleResponse,
    UpsertWeaviateMessageRequest,
    UpsertWeaviateResourceRequest,
)
from omnibox_wizard.wizard.config import ENV_PREFIX
from omnibox_wizard.wizard.search.paginator import FilteredSearchPaginator
from omnibox_wizard.worker.agent.chat_title_generator import (
    ChatTitleGenerateOutput,
    ChatTitleGenerator,
)
from omnibox_wizard.worker.config import TaskConfig, WorkerConfig
from omnibox_wizard.worker.functions.rss_item_parser import RssItemParser
from omnibox_wizard.worker.worker import compute_supported_functions
from wizard_common.grimoire.config import GrimoireAgentConfig, RelevanceConfig
from wizard_common.grimoire.entity.index_record import IndexRecordType
from wizard_common.grimoire.entity.message import Message
from wizard_common.grimoire.retriever.relevance import RelevanceChecker
from wizard_common.grimoire.retriever.weaviate_vector_db import WeaviateVectorDB

dumps = partial(lib_dumps, ensure_ascii=False, separators=(",", ":"))
internal_router = APIRouter(prefix="/internal/api/v1/wizard")
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 128
vector_db: WeaviateVectorDB
title_generator: ChatTitleGenerator
rss_item_parser: RssItemParser
relevance_checker: RelevanceChecker | None = None
relevance_config = RelevanceConfig()
search_paginator: FilteredSearchPaginator | None = None
capabilities: dict = {}


async def init(_):
    global title_generator, vector_db, rss_item_parser, capabilities
    global relevance_checker, relevance_config, search_paginator
    loader = Loader(GrimoireAgentConfig, env_prefix=ENV_PREFIX)
    config: GrimoireAgentConfig = loader.load()

    title_generator = ChatTitleGenerator(config.grimoire.openai)
    vector_db = WeaviateVectorDB(config.vector)
    relevance_config = config.tools.relevance
    relevance_checker = RelevanceChecker(relevance_config)
    search_paginator = FilteredSearchPaginator(
        vector_db, relevance_checker, relevance_config
    )

    worker_config: WorkerConfig = Loader(WorkerConfig, env_prefix=ENV_PREFIX).load()
    rss_item_parser = RssItemParser(worker_config)

    task_config = Loader(TaskConfig, env_prefix=f"{ENV_PREFIX}_TASK").load()
    supported = compute_supported_functions(task_config)
    capabilities = {"functions": supported}


async def internal_shutdown(_):
    global relevance_checker, search_paginator
    if relevance_checker is not None:
        await relevance_checker.aclose()
        relevance_checker = None
    search_paginator = None


@internal_router.post("/title", tags=["LLM"], response_model=TitleResponse)
async def title(request: CommonAITextRequest):
    output: ChatTitleGenerateOutput = await title_generator.ainvoke(
        {
            "text": request.text,
            "lang": request.lang or "简体中文",
        }
    )
    return TitleResponse(title=output.title)


@internal_router.post("/rss/parse", tags=["RSS"], response_model=RssItemParseResponse)
async def parse_rss_item(
    request: RssItemParseRequest,
    trace_info: TraceInfo = Depends(get_trace_info),
):
    markdown = await rss_item_parser.parse(request.url, request.content, trace_info)
    return RssItemParseResponse(markdown=markdown)


@internal_router.post("/search", tags=[], response_model=SearchResponse)
async def search(request: SearchRequest):
    if request.type == IndexRecordType.chunk and search_paginator is not None:
        page = await search_paginator.paginate(
            query=request.query,
            namespace_id=request.namespace_id,
            user_id=request.user_id,
            offset=request.offset,
            limit=request.limit,
            conversation_ids=request.conversation_ids,
            exclude_conversation_ids=request.exclude_conversation_ids,
            resource_ids=request.resource_ids,
        )
        return SearchResponse(
            records=page.records, total=page.total, has_more=page.has_more
        )
    records = await vector_db.search(
        conversation_ids=request.conversation_ids,
        exclude_conversation_ids=request.exclude_conversation_ids,
        query=request.query,
        namespace_id=request.namespace_id,
        user_id=request.user_id,
        record_type=request.type,
        offset=request.offset,
        limit=request.limit,
        resource_ids=request.resource_ids,
    )
    return SearchResponse(
        records=records, total=None, has_more=len(records) >= request.limit
    )


@internal_router.post("/upsert_weaviate/resource", tags=[])
async def upsert_weaviate_resource(request: UpsertWeaviateResourceRequest):
    chunks = build_resource_chunks(
        title=request.title,
        content=request.content,
        metadata={
            "resource_id": request.resource_id,
            "parent_id": request.parent_id,
            "resource_tag_ids": request.resource_tag_ids,
            "resource_tag_names": request.resource_tag_names,
        },
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
    )
    await vector_db.remove_chunks(request.namespace_id, request.resource_id)
    await vector_db.insert_chunks(request.namespace_id, chunks)
    return {"success": True}


@internal_router.post("/upsert_weaviate/message", tags=[])
async def upsert_weaviate_message(
    request: UpsertWeaviateMessageRequest,
    _trace_info: TraceInfo = Depends(get_trace_info),
):
    message = Message(**request.message.model_dump())
    await vector_db.upsert_message(request.namespace_id, request.user_id, message)
    return {"success": True}


@internal_router.get("/functions")
async def get_functions():
    return capabilities


class ClearMessageIndexRequest(BaseModel):
    namespace_id: str = Field(min_length=1)


@internal_router.post("/clear_message_index")
async def clear_message_index(request: ClearMessageIndexRequest):
    deleted = await vector_db.remove_message_vectors(request.namespace_id)
    return {"deleted": deleted}
