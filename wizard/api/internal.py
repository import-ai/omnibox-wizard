from functools import partial
from json import dumps as lib_dumps

from fastapi import APIRouter, Depends

from common.config_loader import Loader
from common.trace_info import TraceInfo
from wizard.api.depends import get_trace_info
from wizard.api.entity import TitleResponse, CommonAITextRequest, TagsResponse
from wizard.config import Config, ENV_PREFIX
from wizard.grimoire.common_ai import CommonAI

dumps = partial(lib_dumps, ensure_ascii=False, separators=(",", ":"))
internal_router = APIRouter(prefix="/internal/api/v1/wizard")
common_ai: CommonAI = ...


async def init():
    global common_ai
    loader = Loader(Config, env_prefix=ENV_PREFIX)
    config: Config = loader.load()

    common_ai = CommonAI(config.grimoire.openai)


@internal_router.post("/title", tags=["LLM"], response_model=TitleResponse)
async def title(request: CommonAITextRequest, trace_info: TraceInfo = Depends(get_trace_info)):
    return TitleResponse(title=await common_ai.title(request.text, trace_info=trace_info))


@internal_router.get("/tags", tags=["LLM"], response_model=TagsResponse)
async def tags(request: CommonAITextRequest, trace_info: TraceInfo = Depends(get_trace_info)):
    return TagsResponse(tags=await common_ai.tags(request.text, trace_info=trace_info))
