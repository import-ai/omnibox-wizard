from functools import partial
from json import dumps as lib_dumps

from fastapi import APIRouter, Depends

from common.config_loader import Loader
from common.trace_info import TraceInfo
from wizard.api.depends import get_trace_info
from wizard.api.entity import (
    SearchRequest,
    SearchResponse,
    TitleResponse,
    CommonAITextRequest,
    TagsResponse,
)
from wizard.config import Config, ENV_PREFIX
from wizard.grimoire.common_ai import CommonAI
from wizard.grimoire.retriever.meili_vector_db import MeiliVectorDB

dumps = partial(lib_dumps, ensure_ascii=False, separators=(",", ":"))
internal_router = APIRouter(prefix="/internal/api/v1/wizard")
common_ai: CommonAI = ...
vector_db: MeiliVectorDB


async def init():
    global common_ai
    global vector_db
    loader = Loader(Config, env_prefix=ENV_PREFIX)
    config: Config = loader.load()

    common_ai = CommonAI(config.grimoire.openai)
    vector_db = MeiliVectorDB(config.vector)


@internal_router.post("/title", tags=["LLM"], response_model=TitleResponse)
async def title(
    request: CommonAITextRequest, trace_info: TraceInfo = Depends(get_trace_info)
):
    return TitleResponse(
        title=await common_ai.title(request.text, trace_info=trace_info)
    )


@internal_router.get("/tags", tags=["LLM"], response_model=TagsResponse)
async def tags(
    request: CommonAITextRequest, trace_info: TraceInfo = Depends(get_trace_info)
):
    return TagsResponse(tags=await common_ai.tags(request.text, trace_info=trace_info))


@internal_router.get("/search", tags=[], response_model=SearchResponse)
async def search(
    request: SearchRequest, trace_info: TraceInfo = Depends(get_trace_info)
):
    records = await vector_db.search(
        query=request.query,
        namespace_id=request.namespace_id,
        user_id=request.user_id,
        type=request.type,
        offset=request.offset,
        limit=request.limit,
    )
    return SearchResponse(records=records)
