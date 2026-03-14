from functools import partial
from json import dumps as lib_dumps
from typing import AsyncIterator

import openai
from fastapi import APIRouter, Depends
from opentelemetry import trace
from pydantic import BaseModel
from sse_starlette import EventSourceResponse

from common.config_loader import Loader
from common.trace_info import TraceInfo
from omnibox_wizard.wizard.api.depends import get_trace_info
from omnibox_wizard.wizard.config import ENV_PREFIX
from wizard_common.grimoire.agent.ask import Ask
from wizard_common.grimoire.config import GrimoireAgentConfig
from wizard_common.grimoire.agent.write import Write
from wizard_common.grimoire.base_streamable import BaseStreamable, ChatResponse
from wizard_common.grimoire.entity.api import AgentRequest, BaseChatRequest

dumps = partial(lib_dumps, ensure_ascii=False, separators=(",", ":"))
wizard_router = APIRouter(prefix="/wizard")
ask: Ask = ...
write: Write = ...
tracer = trace.get_tracer("wizard-router")


async def init(app):
    global ask, write
    loader = Loader(GrimoireAgentConfig, env_prefix=ENV_PREFIX)
    config: GrimoireAgentConfig = loader.load()

    ask = Ask(config)
    write = Write(config)


async def stream_wrapper(
    request: BaseModel, stream: AsyncIterator[ChatResponse], trace_info: TraceInfo
) -> AsyncIterator[dict]:
    span = trace.get_current_span()
    trace_info.debug({"request": request.model_dump(exclude_none=True)})
    error: Exception | None = None
    error_message: str | None = ""
    try:
        async for delta in stream:
            yield delta.model_dump(exclude_none=True)
    except openai.APIError as e:
        error, error_message = e, "Inappropriate content"
    except Exception as e:
        error, error_message = e, "Unknown error"
    if error:
        span.record_exception(error)
        span.set_attribute("error_message", error_message)
        trace_info.exception(
            {
                "exception_class": error.__class__.__name__,
                "exception_message": str(error),
                "request": request.model_dump(exclude_none=True),
            }
        )
        yield {"response_type": "error", "message": error_message}
    yield {"response_type": "done"}


async def call_stream(
    s: BaseStreamable, request: BaseChatRequest, trace_info: TraceInfo
) -> AsyncIterator[dict]:
    with tracer.start_as_current_span("wizard.call_stream"):
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
async def api_ask(
    request: AgentRequest, trace_info: TraceInfo = Depends(get_trace_info)
):
    return streaming_response(call_stream(ask, request, trace_info))


@wizard_router.post("/write", tags=["LLM"], response_model=ChatResponse)
async def api_write(
    request: AgentRequest, trace_info: TraceInfo = Depends(get_trace_info)
):
    return streaming_response(call_stream(write, request, trace_info))
