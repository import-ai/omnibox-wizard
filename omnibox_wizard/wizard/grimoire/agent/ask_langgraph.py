"""
Ask Agent implemented with LangGraph.

A simplified implementation using native LangGraph patterns:
- Minimal state: only messages
- Two nodes: call_llm, execute_tools
- Streaming via async queue passed through RunnableConfig
"""

import asyncio
import json as jsonlib
import time
from functools import partial
from typing import TypedDict, Literal, AsyncIterable
from uuid import uuid4

from langgraph.graph import StateGraph
from langchain_core.runnables import RunnableConfig
from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall
from opentelemetry import propagate, trace

from common import project_root
from common.template_parser import TemplateParser
from common.trace_info import TraceInfo
from omnibox_wizard.wizard.config import Config
from omnibox_wizard.wizard.grimoire.agent.stream_parser import StreamParser
from omnibox_wizard.wizard.grimoire.agent.tool_executor import ToolExecutor
from omnibox_wizard.wizard.grimoire.base_streamable import ChatResponse
from omnibox_wizard.wizard.grimoire.entity.api import (
    ChatDeltaResponse,
    AgentRequest,
    ChatBOSResponse,
    ChatEOSResponse,
    MessageDto,
    ChatRequestOptions,
    ChatBaseResponse,
)
from omnibox_wizard.wizard.grimoire.entity.tools import (
    ToolExecutorConfig,
    BaseResourceTool,
)
from omnibox_wizard.wizard.grimoire.retriever.base import BaseRetriever
from omnibox_wizard.wizard.grimoire.retriever.reranker import (
    get_tool_executor_config,
    get_merged_description,
)
from omnibox_wizard.wizard.grimoire.entity.tools import ProductDocsTool
from omnibox_wizard.wizard.grimoire.agent.agent import UserQueryPreprocessor, BaseSearchableAgent

json_dumps = partial(jsonlib.dumps, ensure_ascii=False, separators=(",", ":"))
tracer = trace.get_tracer(__name__)

# ============== State ==============
class AgentState(TypedDict):
    """Minimal state - just the conversation messages."""
    messages: list[MessageDto]


# ============== Helpers ==============
def add_message(messages: list[MessageDto], new: MessageDto) -> list[MessageDto]:
    """Reducer to append a message."""
    return messages + [new]


async def emit(config: RunnableConfig, response: ChatBaseResponse) -> None:
    """Emit a response to the stream queue."""
    queue: asyncio.Queue = config["configurable"]["queue"]
    await queue.put(response)


async def emit_complete_message(
    config: RunnableConfig, message: dict, attrs: dict | None = None
) -> None:
    """Emit BOS, Delta, and EOS for a complete message."""
    await emit(config, ChatBOSResponse(role=message["role"]))
    await emit(config, ChatDeltaResponse.model_validate(
        {"message": message} | ({"attrs": attrs} if attrs else {})
    ))
    await emit(config, ChatEOSResponse())


def _accumulate_tool_call(assistant_message: dict, tc: ChoiceDeltaToolCall) -> None:
    """Accumulate native tool call deltas into assistant message."""
    while tc.index >= len(assistant_message.get("tool_calls", [])):
        assistant_message.setdefault("tool_calls", []).append({})

    if tc.id:
        assistant_message["tool_calls"][tc.index]["id"] = tc.id
    if tc.type:
        assistant_message["tool_calls"][tc.index]["type"] = tc.type
    if tc.function:
        fn = assistant_message["tool_calls"][tc.index].setdefault("function", {})
        if tc.function.name:
            fn["name"] = fn.get("name", "") + tc.function.name
        if tc.function.arguments:
            fn["arguments"] = fn.get("arguments", "") + tc.function.arguments


def _parse_custom_tool_calls(tool_calls_buffer: str) -> list[dict]:
    """Parse custom tool calls from buffer."""
    tool_calls = []
    for line in tool_calls_buffer.splitlines():
        if json_str := line.strip():
            try:
                tc_json = jsonlib.loads(json_str)
                tc_json["arguments"] = json_dumps(tc_json["arguments"])
                tool_calls.append({
                    "id": str(uuid4()).replace("-", ""),
                    "type": "function",
                    "function": tc_json,
                })
            except jsonlib.JSONDecodeError:
                continue
    return tool_calls


# ============== Nodes ==============
async def call_llm(state: AgentState, config: RunnableConfig) -> dict:
    """Call LLM with streaming output."""
    agent: "AskLangGraph" = config["configurable"]["agent"]
    agent_request: AgentRequest = config["configurable"]["agent_request"]
    trace_info: TraceInfo = config["configurable"]["trace_info"]
    tool_executor: ToolExecutor = config["configurable"]["tool_executor"]
    custom_tool_call: bool = config["configurable"]["custom_tool_call"]

    messages = list(state["messages"])

    with tracer.start_as_current_span("call_llm") as span:
        # Convert to OpenAI format
        openai_messages = UserQueryPreprocessor.message_dtos_to_openai_messages(
            messages, original_tools=agent_request.tools, tool_executor=tool_executor
        )

        # Get OpenAI client
        openai = agent.openai.get_config("large", default=agent.openai.default)
        kwargs: dict = {}

        if agent_request.enable_thinking is not None:
            if large_thinking := agent.openai.get_config("large", thinking=True, default=None):
                if agent_request.enable_thinking:
                    openai = large_thinking
            else:
                kwargs["extra_body"] = {"enable_thinking": agent_request.enable_thinking}

        if tool_executor and tool_executor.tools and not custom_tool_call:
            kwargs["tools"] = tool_executor.tools

        # Prepare headers
        headers = {}
        propagate.inject(headers)
        if trace_info:
            headers["X-Request-Id"] = trace_info.request_id

        # Call OpenAI
        assistant_message: dict = {"role": "assistant"}
        start_time = time.time()
        ttft = -1.0

        openai_response: AsyncStream[ChatCompletionChunk] = await openai.chat(
            messages=openai_messages,
            stream=True,
            extra_headers=headers if headers else None,
            **kwargs,
        )

        await emit(config, ChatBOSResponse(role="assistant"))

        tool_calls_buffer = ""
        stream_parser = StreamParser() if custom_tool_call else None

        async for chunk in openai_response:
            delta = chunk.choices[0].delta

            if ttft < 0:
                ttft = time.time() - start_time
                span.set_attribute("ttft", ttft)

            # Handle native tool_calls
            if delta.tool_calls:
                _accumulate_tool_call(assistant_message, delta.tool_calls[0])

            # Handle content
            for key in ["content", "reasoning_content"]:
                if hasattr(delta, key) and (v := getattr(delta, key)):
                    if custom_tool_call and key == "content":
                        # Parse custom tool calls from content
                        normal_content = ""
                        for op in stream_parser.parse(v):
                            if op["tag"] == "tool_call":
                                tool_calls_buffer += op["delta"]
                            elif op["tag"] != "think":
                                normal_content += op["delta"]

                        if normal_content:
                            assistant_message[key] = assistant_message.get(key, "") + normal_content
                            await emit(config, ChatDeltaResponse.model_validate(
                                {"message": {key: normal_content}}
                            ))
                    else:
                        assistant_message[key] = assistant_message.get(key, "") + v
                        await emit(config, ChatDeltaResponse.model_validate(
                            {"message": {key: v}}
                        ))

        # Parse tool calls from buffer (custom mode)
        if tool_calls_buffer:
            for tc in _parse_custom_tool_calls(tool_calls_buffer):
                assistant_message.setdefault("tool_calls", []).append(tc)

        # Emit tool_calls if present
        if tool_calls := assistant_message.get("tool_calls"):
            await emit(config, ChatDeltaResponse.model_validate(
                {"message": {"tool_calls": tool_calls}}
            ))

        await emit(config, ChatEOSResponse())

        span.set_attributes({
            "model": openai.model,
            "messages_count": len(openai_messages),
            "has_tool_calls": bool(assistant_message.get("tool_calls")),
        })

    return {"messages": messages + [MessageDto.model_validate({"message": assistant_message})]}


async def execute_tools(state: AgentState, config: RunnableConfig) -> dict:
    """Execute tool calls from the last assistant message."""
    tool_executor: ToolExecutor = config["configurable"]["tool_executor"]
    trace_info: TraceInfo = config["configurable"]["trace_info"]

    messages = list(state["messages"])

    with tracer.start_as_current_span("execute_tools"):
        async for chunk in tool_executor.astream(
            messages, trace_info=trace_info.get_child("tool_executor")
        ):
            if isinstance(chunk, MessageDto):
                messages.append(chunk)
            elif isinstance(chunk, ChatBaseResponse):
                await emit(config, chunk)

    return {"messages": messages}


# ============== Routing ==============
def should_continue(state: AgentState) -> Literal["execute_tools", "__end__"]:
    """Route based on whether the last message has tool calls."""
    last_msg = state["messages"][-1]
    if last_msg.message.get("tool_calls"):
        return "execute_tools"
    return "__end__"


# ============== Graph Builder ==============
def build_graph() -> StateGraph:
    """Build the agent graph."""
    graph = StateGraph(AgentState)

    graph.add_node("call_llm", call_llm)
    graph.add_node("execute_tools", execute_tools)

    graph.set_entry_point("call_llm")
    graph.add_conditional_edges("call_llm", should_continue)
    graph.add_edge("execute_tools", "call_llm")

    return graph.compile()


# ============== Agent Class ==============
class AskLangGraph(BaseSearchableAgent):
    """Ask Agent implemented with LangGraph."""

    def __init__(self, config: Config):
        super().__init__(config)

        # LangGraph-specific attributes
        self.openai = config.grimoire.openai
        self.template_parser = TemplateParser(
            base_dir=project_root.path("omnibox_wizard/resources/prompt_templates")
        )
        self.system_prompt_template = self.template_parser.get_template("ask.j2")
        self.custom_tool_call: bool | None = config.grimoire.custom_tool_call
        self.graph = build_graph()
 
    def get_tool_executor(
        self,
        options: ChatRequestOptions,
        trace_info: TraceInfo,
        wrap_reranker: bool = True,
        messages: list[MessageDto] = None,
    ) -> ToolExecutor:
        """Create ToolExecutor from request options.

        - Search tools (private_search, web_search): based on options.tools, wrapped by reranker
        - Resource tools: product_docs is ALWAYS available, others only when private_search is present
        """
        search_configs: list[ToolExecutorConfig] = []
        resource_configs: list[ToolExecutorConfig] = []
        private_search_tool = None

        # Search tools: based on agent_request.tools
        for tool in options.tools or []:
            if tool.name in self.retriever_mapping:
                cfg = self.retriever_mapping[tool.name].get_tool_executor_config(
                    tool, trace_info=trace_info.get_child(tool.name)
                )
                search_configs.append(cfg)
                if tool.name == "private_search":
                    private_search_tool = tool

        # Apply reranker to search tools ONLY (resource tools not wrapped)
        if options.merge_search and search_configs:
            search_configs = [get_tool_executor_config(search_configs, self.reranker)]
        elif wrap_reranker:
            for cfg in search_configs:
                cfg["func"] = self.reranker.wrap(
                    func=cfg["func"],
                    trace_info=trace_info.get_child("reranker"),
                )

        # Create ToolExecutor with search configs first
        all_configs = search_configs
        tool_executor = ToolExecutor({c["name"]: c for c in all_configs})

        # 1. Rebuild cite_id mapping from historical messages (multi-turn support)
        if messages:
            for msg in messages:
                if msg.attrs and msg.attrs.citations:
                    for citation in msg.attrs.citations:
                        # citation.link is resource_id
                        tool_executor.register_resource_with_id(citation.link, citation.id)
        # 2. Initialize cite_id for visible_resources
        if private_search_tool and private_search_tool.visible_resources:
            for resource in private_search_tool.visible_resources:
                tool_executor.register_resource(resource.id)

        # Resource tools: product_docs is ALWAYS available (independent of private_search)
        # Other resource tools only when private_search is present

        # Always add product_docs (default enabled, now as resource handler)
        cfg = self.resource_handlers["product_docs"].get_tool_executor_config(
            ProductDocsTool(),
            trace_info=trace_info.get_child("product_docs"),
            lang=options.lang or "简体中文",
        )
        resource_configs.append(cfg)

        # Add other resource tools ONLY when private_search is present
        if private_search_tool:
            # Create a BaseResourceTool with info from private_search
            resource_tool = BaseResourceTool(
                name="get_resources",  # placeholder, will be overwritten
                namespace_id=private_search_tool.namespace_id,
                visible_resources=private_search_tool.visible_resources,
            )
            for name, handler in self.resource_handlers.items():
                if name == "product_docs":
                    continue  # Already added above
                cfg = handler.get_tool_executor_config(
                    resource_tool,
                    trace_info=trace_info.get_child(name),
                    tool_executor=tool_executor,
                )
                resource_configs.append(cfg)

        # Add resource configs to tool_executor
        for cfg in resource_configs:
            tool_executor.config[cfg["name"]] = cfg
            tool_executor.tools.append(cfg["schema"])

        return tool_executor

    async def _prepare_messages(
        self,
        agent_request: AgentRequest,
        tool_executor: ToolExecutor,
        queue: asyncio.Queue,
    ) -> list[MessageDto]:
        """Prepare initial messages (system prompt + user query)."""
        messages: list[MessageDto] = list(agent_request.messages or [])

        # Build tool list
        all_tools = self.all_tools
        if agent_request.merge_search:
            all_tools = [
                BaseRetriever.generate_schema("search", get_merged_description(all_tools))
            ]

        # Add system message if needed
        if not messages:
            if self.custom_tool_call:
                prompt: str = self.template_parser.render_template(
                    self.system_prompt_template,
                    lang=agent_request.lang or "简体中文",
                    tools="\n".join(json_dumps(tool) for tool in all_tools),
                    part_1_enabled=True,
                    part_2_enabled=True,
                )
                system_msg = {"role": "system", "content": prompt}
                await emit_complete_message(
                    {"configurable": {"queue": queue}}, system_msg
                )
                messages.append(MessageDto.model_validate({"message": system_msg}))
            else:
                for i in range(2):
                    prompt: str = self.template_parser.render_template(
                        self.system_prompt_template,
                        lang=agent_request.lang or "简体中文",
                        **{f"part_{i + 1}_enabled": True},
                    )
                    system_msg: dict = {"role": "system", "content": prompt}
                    await emit_complete_message(
                        {"configurable": {"queue": queue}}, system_msg
                    )
                    messages.append(MessageDto.model_validate({"message": system_msg}))

        # Add user message if needed
        if messages[-1].message["role"] != "user":
            user_dto = MessageDto.model_validate({
                "message": {"role": "user", "content": agent_request.query},
                "attrs": agent_request.model_dump(exclude_none=True, mode="json"),
            })
            messages.append(user_dto)
            await emit_complete_message(
                {"configurable": {"queue": queue}}, user_dto.message, user_dto.attrs
            )

        # Preprocess with related_resources
        await UserQueryPreprocessor.with_related_resources_(
            messages[-1], tool_executor.config
        )

        return messages

    async def astream(
        self, trace_info: TraceInfo, agent_request: AgentRequest
    ) -> AsyncIterable[ChatResponse]:
        """Stream responses from the Ask Agent."""
        with tracer.start_as_current_span("agent.astream") as span:
            span.set_attributes({
                "conversation_id": agent_request.conversation_id,
                "custom_tool_call": str(self.custom_tool_call),
            })

            # Create queue for streaming responses
            queue: asyncio.Queue[ChatBaseResponse | None] = asyncio.Queue()

            # Create tool executor
            tool_executor = self.get_tool_executor(
                agent_request,
                trace_info=trace_info,
                messages=agent_request.messages,
            )

            # Prepare initial messages
            initial_messages = await self._prepare_messages(
                agent_request, tool_executor, queue
            )

            # Yield any messages emitted during preparation
            while not queue.empty():
                yield queue.get_nowait()

            # Run graph in background
            async def run_graph():
                try:
                    await self.graph.ainvoke(
                        {"messages": initial_messages},
                        config={
                            "configurable": {
                                "queue": queue,
                                "agent": self,
                                "agent_request": agent_request,
                                "trace_info": trace_info,
                                "tool_executor": tool_executor,
                                "custom_tool_call": self.custom_tool_call,
                            }
                        },
                    )
                finally:
                    await queue.put(None)

            task = asyncio.create_task(run_graph())

            # Stream responses from queue
            try:
                while True:
                    response = await queue.get()
                    if response is None:
                        break
                    yield response
            finally:
                await task
