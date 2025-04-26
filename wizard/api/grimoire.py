from functools import partial
from json import dumps as lib_dumps
from typing import AsyncIterator, Union

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from common.config_loader import Loader
from common.trace_info import TraceInfo
from wizard.api.depends import get_trace_info
from wizard.config import Config, ENV_PREFIX
from wizard.grimoire.entity.api import ChatRequest, ChatBaseResponse, ChatDeltaResponse, ChatCitationListResponse
from wizard.grimoire.pipeline import Pipeline

dumps = partial(lib_dumps, ensure_ascii=False, separators=(",", ":"))
grimoire_router = APIRouter(prefix="/grimoire")
pipeline: Pipeline = ...


async def init():
    global pipeline
    loader = Loader(Config, env_prefix=ENV_PREFIX)
    config: Config = loader.load()
    pipeline = Pipeline(config)
    await pipeline.async_init()


async def call_stream(p: Pipeline, request: ChatRequest, trace_info: TraceInfo) -> AsyncIterator[dict]:
    try:
        async for delta in p.astream(trace_info, request):
            yield delta.model_dump()
    except Exception as e:
        yield {"response_type": "error", "message": "Unknown error"}
        trace_info.logger.exception({"exception_class": e.__class__.__name__, "exception_message": str(e)})
    yield {"response_type": "done"}


async def sse_format(iterator: AsyncIterator[dict]) -> AsyncIterator[str]:
    async for item in iterator:
        yield f"data: {dumps(item)}\n\n"


@grimoire_router.post("/stream", tags=["LLM"],
                      response_model=Union[ChatBaseResponse, ChatDeltaResponse, ChatCitationListResponse])
async def stream(request: ChatRequest, trace_info: TraceInfo = Depends(get_trace_info)):
    """
    Answer the query based on user's database.
    """
    return StreamingResponse(sse_format(call_stream(pipeline, request, trace_info)), media_type="text/event-stream")
