from functools import partial
from json import dumps as lib_dumps

from fastapi import APIRouter, Depends

from common.config_loader import Loader
from common.trace_info import TraceInfo
from omnibox_wizard.wizard.api.depends import get_trace_info
from omnibox_wizard.wizard.api.entity import (
    SearchRequest,
    SearchResponse,
    TitleResponse,
    CommonAITextRequest,
    TagsResponse,
)
from omnibox_wizard.wizard.config import ENV_PREFIX
from wizard_common.grimoire.common_ai import CommonAI
from wizard_common.grimoire.config import GrimoireAgentConfig
from wizard_common.grimoire.retriever.meili_vector_db import MeiliVectorDB

dumps = partial(lib_dumps, ensure_ascii=False, separators=(",", ":"))
internal_router = APIRouter(prefix="/internal/api/v1/wizard")
common_ai: CommonAI = ...
vector_db: MeiliVectorDB


async def init(app):
    global common_ai
    global vector_db
    loader = Loader(GrimoireAgentConfig, env_prefix=ENV_PREFIX)
    config: GrimoireAgentConfig = loader.load()

    common_ai = CommonAI(config.grimoire.openai)
    vector_db = MeiliVectorDB(config.vector)


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
