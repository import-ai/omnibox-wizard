from functools import partial
from json import dumps as lib_dumps
from typing import AsyncIterator, Union

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from common.config_loader import Loader
from common.trace_info import TraceInfo
from wizard.api.depends import get_trace_info
from wizard.api.entity import TitleResponse, CommonAITextRequest, TagsResponse
from wizard.config import Config, ENV_PREFIX
from wizard.grimoire.agent.agent import Agent
from wizard.grimoire.base_streamable import BaseStreamable, ChatResponse
from wizard.grimoire.common_ai import CommonAI
from wizard.grimoire.entity.api import (
    ChatRequest, ChatBaseResponse, ChatDeltaResponse, AgentRequest, BaseChatRequest
)
from wizard.grimoire.pipeline import Pipeline

dumps = partial(lib_dumps, ensure_ascii=False, separators=(",", ":"))
wizard_router = APIRouter(prefix="/wizard")
pipeline: Pipeline = ...
agent: Agent = ...
common_ai: CommonAI = ...


async def init():
    global agent, pipeline, common_ai
    loader = Loader(Config, env_prefix=ENV_PREFIX)
    config: Config = loader.load()

    pipeline = Pipeline(config)
    agent = Agent(config.grimoire.openai["large"], config.tools, config.vector)
    common_ai = CommonAI(config.grimoire.openai)


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


@wizard_router.post("/stream", tags=["LLM"],
                    response_model=Union[ChatBaseResponse, ChatDeltaResponse])
async def stream(request: ChatRequest, trace_info: TraceInfo = Depends(get_trace_info)):
    """
    Answer the query based on user's database.
    """
    return StreamingResponse(sse_format(call_stream(pipeline, request, trace_info)), media_type="text/event-stream")


@wizard_router.post("/ask", tags=["LLM"], response_model=ChatResponse)
async def ask(request: AgentRequest, trace_info: TraceInfo = Depends(get_trace_info)):
    return StreamingResponse(sse_format(call_stream(agent, request, trace_info)), media_type="text/event-stream")


@wizard_router.post("/title", tags=["LLM"], response_model=TitleResponse)
async def title(request: CommonAITextRequest, trace_info: TraceInfo = Depends(get_trace_info)):
    return TitleResponse(title=await common_ai.title(request.text, trace_info=trace_info))


@wizard_router.get("/tags", tags=["LLM"], response_model=TagsResponse)
async def tags(request: CommonAITextRequest, trace_info: TraceInfo = Depends(get_trace_info)):
    return TagsResponse(tags=await common_ai.tags(request.text, trace_info=trace_info))
