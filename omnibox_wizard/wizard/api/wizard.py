from functools import partial
from json import dumps as lib_dumps

from fastapi import APIRouter, Depends, FastAPI
from opentelemetry import trace

from common.config_loader import Loader
from common.trace_info import TraceInfo
from omnibox_wizard.wizard.api.depends import get_trace_info
from omnibox_wizard.wizard.config import ENV_PREFIX
from wizard_common.grimoire.agent.ask import Ask
from wizard_common.grimoire.agent.write import Write
from wizard_common.grimoire.base_streamable import ChatResponse
from wizard_common.grimoire.config import GrimoireAgentConfig
from wizard_common.grimoire.entity.api import AgentRequest
from wizard_common.wizard.utils import call_stream, streaming_response

dumps = partial(lib_dumps, ensure_ascii=False, separators=(",", ":"))
wizard_router = APIRouter(prefix="/wizard")
ask: Ask = ...
write: Write = ...
tracer = trace.get_tracer("wizard-router")


async def init(_: FastAPI):
    global ask, write
    loader = Loader(GrimoireAgentConfig, env_prefix=ENV_PREFIX)
    config: GrimoireAgentConfig = loader.load()

    ask = Ask(config)
    write = Write(config)


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
