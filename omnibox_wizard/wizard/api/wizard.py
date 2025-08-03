from functools import partial
from json import dumps as lib_dumps
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from omnibox_wizard.common.config_loader import Loader
from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.wizard.api.depends import get_trace_info
from omnibox_wizard.wizard.config import Config, ENV_PREFIX
from omnibox_wizard.wizard.grimoire.agent.ask import Ask
from omnibox_wizard.wizard.grimoire.agent.write import Write
from omnibox_wizard.wizard.grimoire.base_streamable import BaseStreamable, ChatResponse
from omnibox_wizard.wizard.grimoire.entity.api import (
    AgentRequest, BaseChatRequest
)

dumps = partial(lib_dumps, ensure_ascii=False, separators=(",", ":"))
wizard_router = APIRouter(prefix="/wizard")
ask: Ask = ...
write: Write = ...


async def init():
    global ask, write
    loader = Loader(Config, env_prefix=ENV_PREFIX)
    config: Config = loader.load()

    ask = Ask(config)
    write = Write(config)


async def stream_wrapper(
        request: BaseModel,
        stream: AsyncIterator[ChatResponse],
        trace_info: TraceInfo
) -> AsyncIterator[dict]:
    trace_info.debug({"request": request.model_dump(exclude_none=True)})
    try:
        async for delta in stream:
            yield delta.model_dump(exclude_none=True)
    except Exception as e:
        yield {"response_type": "error", "message": "Unknown error"}
        trace_info.exception({
            "exception_class": e.__class__.__name__,
            "exception_message": str(e),
            "request": request.model_dump(exclude_none=True),
        })
    yield {"response_type": "done"}


async def call_stream(s: BaseStreamable, request: BaseChatRequest, trace_info: TraceInfo) -> AsyncIterator[dict]:
    stream = s.astream(trace_info.get_child("agent"), request)
    async for delta in stream_wrapper(request, stream, trace_info):  # noqa
        yield delta


async def sse_format(iterator: AsyncIterator[dict]) -> AsyncIterator[str]:
    async for item in iterator:
        yield f"data: {dumps(item)}\n\n"


async def sse_dumps(iterator: AsyncIterator[dict]) -> AsyncIterator[str]:
    async for item in iterator:
        yield dumps(item)


def streaming_response(iterator: AsyncIterator[dict]) -> EventSourceResponse:
    return EventSourceResponse(sse_dumps(iterator))


@wizard_router.post("/ask", tags=["LLM"], response_model=ChatResponse)
async def api_ask(request: AgentRequest, trace_info: TraceInfo = Depends(get_trace_info)):
    return streaming_response(call_stream(ask, request, trace_info))


@wizard_router.post("/write", tags=["LLM"], response_model=ChatResponse)
async def api_write(request: AgentRequest, trace_info: TraceInfo = Depends(get_trace_info)):
    return streaming_response(call_stream(write, request, trace_info))
