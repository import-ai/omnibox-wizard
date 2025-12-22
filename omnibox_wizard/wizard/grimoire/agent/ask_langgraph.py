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
from omnibox_wizard.wizard.grimoire.base_streamable import BaseStreamable, ChatResponse
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
    PrivateSearchResourceType,
)
from omnibox_wizard.wizard.grimoire.retriever.base import BaseRetriever
from omnibox_wizard.wizard.grimoire.retriever.meili_vector_db import MeiliVectorRetriever
from omnibox_wizard.wizard.grimoire.retriever.reranker import (
    get_tool_executor_config,
    get_merged_description,
    Reranker,
)
from omnibox_wizard.wizard.grimoire.retriever.searxng import SearXNG
from omnibox_wizard.wizard.grimoire.client.resource_api import ResourceAPIClient
from omnibox_wizard.wizard.grimoire.retriever.resource import (
    BaseResourceHandler,
    GetResourcesHandler,
    GetChildrenHandler,
    GetParentHandler,
    FilterByTimeHandler,
    FilterByTagHandler,
)
from omnibox_wizard.wizard.grimoire.agent.agent import UserQueryPreprocessor

json_dumps = partial(jsonlib.dumps, ensure_ascii=False, separators=(",", ":"))
tracer = trace.get_tracer(__name__)


def format_visible_resources(agent_request: AgentRequest) -> str | None:
    """Format visible_resources from private_search for LLM context.

    Returns formatted string or None if no visible_resources.
    """
    # Find private_search tool
    private_search = None
    for tool in agent_request.tools or []:
        if tool.name == "private_search":
            private_search = tool
            break

    if not private_search or not private_search.visible_resources:
        return None

    # Generate short ID mapping (same logic as BaseResourceTool)
    resources_with_ids = []
    resource_counter = 0
    folder_counter = 0

    for resource in private_search.visible_resources:
        if resource.type == PrivateSearchResourceType.FOLDER:
            folder_counter += 1
            short_id = f"f{folder_counter}"
        else:
            resource_counter += 1
            short_id = f"r{resource_counter}"
        resources_with_ids.append({
            "short_id": short_id,
            "name": resource.name,
            "type": resource.type.value,
        })

    if not resources_with_ids:
        return None

    # Separate folders and documents
    folders = [r for r in resources_with_ids if r["type"] == "folder"]
    documents = [r for r in resources_with_ids if r["type"] == "resource"]

    # Format for LLM
    lines = [
        "<available_resources>",
        "User's available folders and documents (use short_id when calling tools):",
        "",
    ]

    if folders:
        lines.append("Folders:")
        for f in folders:
            lines.append(f"  - {f['short_id']}: {f['name']}")

    if documents:
        lines.append("")
        lines.append("Documents:")
        for d in documents:
            lines.append(f"  - {d['short_id']}: {d['name']}")

    lines.extend([
        "",
        "Tool Usage Guide:",
        "- To see folder contents: get_children(folder_short_id) e.g., get_children(namespace_id, resource_id)",
        "- To read document content: get_resources([doc_short_ids]) e.g., get_resources(['r1', 'r2'])",
        "- For time-based queries ('recent', 'this week'): use filter_by_time",
        "- For tag-based queries: use filter_by_tag",
        "- private_search is for keyword search across all documents",
        "</available_resources>",
    ])

    return "\n".join(lines)


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
            messages, original_tools=agent_request.tools
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
                tc: ChoiceDeltaToolCall = delta.tool_calls[0]
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
            for line in tool_calls_buffer.splitlines():
                if json_str := line.strip():
                    try:
                        tc_json = jsonlib.loads(json_str)
                        tc_json["arguments"] = json_dumps(tc_json["arguments"])
                        assistant_message.setdefault("tool_calls", []).append({
                            "id": str(uuid4()).replace("-", ""),
                            "type": "function",
                            "function": tc_json,
                        })
                    except jsonlib.JSONDecodeError:
                        continue

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
class AskLangGraph(BaseStreamable):
    """Ask Agent implemented with LangGraph."""

    def __init__(self, config: Config):
        # Search tools
        self.knowledge_database_retriever = MeiliVectorRetriever(config=config.vector)
        self.web_search_retriever = SearXNG(
            base_url=config.tools.searxng.base_url,
            engines=config.tools.searxng.engines,
        )
        self.reranker = Reranker(config.tools.reranker)

        self.retriever_mapping: dict[str, BaseRetriever] = {
            r.name: r for r in [self.knowledge_database_retriever, self.web_search_retriever]
        }

        # Resource tools
        self.resource_api_client = ResourceAPIClient(config.tools.resource_api)
        self.resource_handlers: dict[str, BaseResourceHandler] = {
            "get_resources": GetResourcesHandler(self.resource_api_client),
            "get_children": GetChildrenHandler(self.resource_api_client),
            "get_parent": GetParentHandler(self.resource_api_client),
            "filter_by_time": FilterByTimeHandler(self.resource_api_client),
            "filter_by_tag": FilterByTagHandler(self.resource_api_client),
        }

        # All tool schemas
        self.all_tools: list[dict] = [
            r.get_schema() for r in self.retriever_mapping.values()
        ] + [h.get_schema() for h in self.resource_handlers.values()]

        # OpenAI client
        self.openai = config.grimoire.openai

        # Template parser
        self.template_parser = TemplateParser(
            base_dir=project_root.path("omnibox_wizard/resources/prompt_templates")
        )
        self.system_prompt_template = self.template_parser.get_template("ask.j2")

        # Custom tool call mode
        self.custom_tool_call = bool | None = config.grimoire.custom_tool_call

        # Build graph
        self.graph = build_graph()

    def get_tool_executor(
        self,
        options: ChatRequestOptions,
        trace_info: TraceInfo,
        wrap_reranker: bool = True,
    ) -> ToolExecutor:
        """Create ToolExecutor from request options.

        - Search tools (private_search, web_search): based on options.tools
        - Resource tools: included when private_search is present
        """
        search_configs: list[ToolExecutorConfig] = []
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

        # Apply reranker to search tools
        if options.merge_search and search_configs:
            search_configs = [get_tool_executor_config(search_configs, self.reranker)]
        elif wrap_reranker:
            for cfg in search_configs:
                cfg["func"] = self.reranker.wrap(
                    func=cfg["func"],
                    trace_info=trace_info.get_child("reranker"),
                )

        # Resource tools: included when private_search is present
        resource_configs: list[ToolExecutorConfig] = []
        if private_search_tool:
            # Create a BaseResourceTool with info from private_search
            resource_tool = BaseResourceTool(
                name="get_resources",  # placeholder, will be overwritten
                namespace_id=private_search_tool.namespace_id,
                visible_resources=private_search_tool.visible_resources,
            )
            resource_configs = [
                handler.get_tool_executor_config(
                    resource_tool, trace_info=trace_info.get_child(name)
                )
                for name, handler in self.resource_handlers.items()
            ]

        all_configs = search_configs + resource_configs
        return ToolExecutor({c["name"]: c for c in all_configs})

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
            prompt = self.template_parser.render_template(
                self.system_prompt_template,
                lang=agent_request.lang or "简体中文",
                tools="\n".join(json_dumps(t) for t in all_tools),
                part_1_enabled=True,
                part_2_enabled=True,
            )
            system_msg = {"role": "system", "content": prompt}
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
        with tracer.start_as_current_span("astream") as span:
            span.set_attributes({
                "conversation_id": agent_request.conversation_id,
                "custom_tool_call": str(self.custom_tool_call),
            })

            # Create queue for streaming responses
            queue: asyncio.Queue[ChatBaseResponse | None] = asyncio.Queue()

            # Create tool executor
            tool_executor = self.get_tool_executor(agent_request, trace_info=trace_info)

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
