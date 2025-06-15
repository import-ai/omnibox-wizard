from functools import partial
from json import dumps as lib_dumps
from typing import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from src.common.config_loader import Loader
from src.common.trace_info import TraceInfo
from src.wizard.api.depends import get_trace_info
from src.wizard.config import Config, ENV_PREFIX
from src.wizard.grimoire.agent.ask import Ask
from src.wizard.grimoire.agent.write import Write
from src.wizard.grimoire.base_streamable import BaseStreamable, ChatResponse
from src.wizard.grimoire.entity.api import (
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

    ask = Ask(
        config.grimoire.openai["large"],
        config.tools,
        config.vector,
        config.tools.reranker,
        config.grimoire.custom_tool_call,
    )
    write = Write(
        config.grimoire.openai["large"],
        config.tools,
        config.vector,
        config.tools.reranker,
        config.grimoire.custom_tool_call,
    )


async def call_stream(s: BaseStreamable, request: BaseChatRequest, trace_info: TraceInfo) -> AsyncIterator[dict]:
    try:
        async for delta in s.astream(trace_info, request):  # noqa
            yield delta.model_dump(exclude_none=True)
    except Exception as e:
        yield {"response_type": "error", "message": "Unknown error"}
        trace_info.logger.exception({"exception_class": e.__class__.__name__, "exception_message": str(e)})
    yield {"response_type": "done"}


async def sse_format(iterator: AsyncIterator[dict]) -> AsyncIterator[str]:
    async for item in iterator:
        yield f"data: {dumps(item)}\n\n"


@wizard_router.post("/ask", tags=["LLM"], response_model=ChatResponse)
async def api_ask(request: AgentRequest, trace_info: TraceInfo = Depends(get_trace_info)):
    return StreamingResponse(sse_format(call_stream(ask, request, trace_info)), media_type="text/event-stream")


@wizard_router.post("/write", tags=["LLM"], response_model=ChatResponse)
async def api_write(request: AgentRequest, trace_info: TraceInfo = Depends(get_trace_info)):
    return StreamingResponse(sse_format(call_stream(write, request, trace_info)), media_type="text/event-stream")
