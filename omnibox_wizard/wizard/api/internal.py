from functools import partial
from json import dumps as lib_dumps

from fastapi import APIRouter, Depends
from langchain_text_splitters import MarkdownTextSplitter

from common.config_loader import Loader
from common.trace_info import TraceInfo
from omnibox_wizard.wizard.api.depends import get_trace_info
from omnibox_wizard.wizard.api.entity import (
    CommonAITextRequest,
    SearchRequest,
    SearchResponse,
    TagsResponse,
    TitleResponse,
    UpsertWeaviateMessageRequest,
    UpsertWeaviateResourceRequest,
)
from omnibox_wizard.wizard.config import ENV_PREFIX
from wizard_common.grimoire.common_ai import CommonAI
from wizard_common.grimoire.config import GrimoireAgentConfig
from wizard_common.grimoire.entity.chunk import Chunk, ChunkType
from wizard_common.grimoire.entity.message import Message
from wizard_common.grimoire.retriever.weaviate_vector_db import WeaviateVectorDB

dumps = partial(lib_dumps, ensure_ascii=False, separators=(",", ":"))
internal_router = APIRouter(prefix="/internal/api/v1/wizard")
common_ai: CommonAI = ...
splitter = MarkdownTextSplitter(chunk_size=1024, chunk_overlap=128)
vector_db: WeaviateVectorDB


async def init(app):
    global common_ai
    global vector_db
    loader = Loader(GrimoireAgentConfig, env_prefix=ENV_PREFIX)
    config: GrimoireAgentConfig = loader.load()

    common_ai = CommonAI(config.grimoire.openai)
    vector_db = WeaviateVectorDB(config.vector)


@internal_router.post("/title", tags=["LLM"], response_model=TitleResponse)
async def title(
    request: CommonAITextRequest, trace_info: TraceInfo = Depends(get_trace_info)
):
    return TitleResponse(
        title=await common_ai.title(
            request.text, lang=request.lang, trace_info=trace_info
        )
    )


@internal_router.post("/tags", tags=["LLM"], response_model=TagsResponse)
async def tags(
    request: CommonAITextRequest, trace_info: TraceInfo = Depends(get_trace_info)
):
    return TagsResponse(
        tags=await common_ai.tags(
            request.text, lang=request.lang, trace_info=trace_info
        )
    )


@internal_router.post("/search", tags=[], response_model=SearchResponse)
async def search(
    request: SearchRequest, trace_info: TraceInfo = Depends(get_trace_info)
):
    records = await vector_db.search(
        query=request.query,
        namespace_id=request.namespace_id,
        user_id=request.user_id,
        record_type=request.type,
        offset=request.offset,
        limit=request.limit,
    )
    return SearchResponse(records=records)


@internal_router.post("/upsert_weaviate/resource", tags=[])
async def upsert_weaviate_resource(
    request: UpsertWeaviateResourceRequest,
    _trace_info: TraceInfo = Depends(get_trace_info),
):
    texts = splitter.split_text(request.content)
    if not texts:
        texts.append("")
    chunks = [
        Chunk(
            title=request.title,
            text=text,
            chunk_type=ChunkType.snippet,
            start_index=request.content.index(text),
            end_index=request.content.index(text) + len(text),
            resource_id=request.resource_id,
            parent_id=request.parent_id,
            resource_tag_ids=request.resource_tag_ids,
            resource_tag_names=request.resource_tag_names,
        )
        for text in texts
    ]
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
