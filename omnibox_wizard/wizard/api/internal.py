from functools import partial
from json import dumps as lib_dumps

from fastapi import APIRouter, Depends

from common.config_loader import Loader
from common.trace_info import TraceInfo
from omnibox_wizard.indexing import build_resource_chunks
from omnibox_wizard.wizard.api.depends import get_trace_info
from omnibox_wizard.wizard.api.entity import (
    CommonAITextRequest,
    SearchRequest,
    SearchResponse,
    TitleResponse,
    UpsertWeaviateMessageRequest,
    UpsertWeaviateResourceRequest,
)
from omnibox_wizard.wizard.config import ENV_PREFIX
from omnibox_wizard.worker.agent.chat_title_generator import (
    ChatTitleGenerateOutput,
    ChatTitleGenerator,
)
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.functions.file_reader import Convertor
from omnibox_wizard.worker.worker import compute_supported_functions
from wizard_common.grimoire.config import GrimoireAgentConfig
from wizard_common.grimoire.entity.message import Message
from wizard_common.grimoire.retriever.weaviate_vector_db import WeaviateVectorDB

dumps = partial(lib_dumps, ensure_ascii=False, separators=(",", ":"))
internal_router = APIRouter(prefix="/internal/api/v1/wizard")
CHUNK_SIZE = 1024
CHUNK_OVERLAP = 128
vector_db: WeaviateVectorDB
title_generator: ChatTitleGenerator
capabilities: dict = {}


async def init(_):
    global title_generator, vector_db, capabilities
    loader = Loader(GrimoireAgentConfig, env_prefix=ENV_PREFIX)
    config: GrimoireAgentConfig = loader.load()

    title_generator = ChatTitleGenerator(config.grimoire.openai)
    vector_db = WeaviateVectorDB(config.vector)

    task_config = Loader(WorkerConfig, env_prefix=ENV_PREFIX).load().task
    supported = compute_supported_functions(task_config)
    capabilities = {"functions": supported}
    if "file_reader" in supported:
        capabilities["file_reader"] = {
            "extensions": Convertor.get_supported_extensions(
                task_config.docling_base_url, task_config.office_operator_base_url
            )
        }


@internal_router.post("/title", tags=["LLM"], response_model=TitleResponse)
async def title(request: CommonAITextRequest):
    output: ChatTitleGenerateOutput = await title_generator.ainvoke(
        {
            "text": request.text,
            "lang": request.lang or "简体中文",
        }
    )
    return TitleResponse(title=output.title)


@internal_router.post("/search", tags=[], response_model=SearchResponse)
async def search(request: SearchRequest):
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
