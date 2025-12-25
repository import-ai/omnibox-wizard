import json as jsonlib
import time
from abc import ABC
from functools import partial
from typing import AsyncIterable, Literal, Iterable
from uuid import uuid4

from openai import AsyncStream
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall
from opentelemetry import propagate, trace

from common import project_root
from common.template_parser import TemplateParser
from common.trace_info import TraceInfo
from common.utils import remove_continuous_break_lines
from omnibox_wizard.wizard.config import Config
from omnibox_wizard.wizard.grimoire.agent.stream_parser import (
    StreamParser,
    DeltaOperation,
)
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
    MessageAttrs,
)
from omnibox_wizard.wizard.grimoire.entity.chunk import ResourceChunkRetrieval
from omnibox_wizard.wizard.grimoire.entity.tools import (
    ToolExecutorConfig,
    ToolDict,
    Resource,
    ALL_TOOLS,
    PrivateSearchResourceType,
    BaseResourceTool,
    RESOURCE_TOOLS,
)
from omnibox_wizard.wizard.grimoire.retriever.base import BaseRetriever
from omnibox_wizard.wizard.grimoire.retriever.meili_vector_db import (
    MeiliVectorRetriever,
)
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

DEFAULT_TOOL_NAME: str = "private_search"
json_dumps = partial(jsonlib.dumps, ensure_ascii=False, separators=(",", ":"))
tracer = trace.get_tracer(__name__)


class UserQueryPreprocessor:
    PRIVATE_SEARCH_TOOL_NAME: str = "private_search"

    @classmethod
    @tracer.start_as_current_span("UserQueryPreprocessor.with_related_resources_")
    async def with_related_resources_(
        cls, message: MessageDto, tool_executor_config: dict[str, ToolExecutorConfig]
    ) -> MessageDto:
        tools = ToolDict(message.attrs.tools or [])
        span = trace.get_current_span()
        span.set_attribute(
            "tool_names", json_dumps([tool.name for tool in message.attrs.tools or []])
        )
        if tool := tools.get(cls.PRIVATE_SEARCH_TOOL_NAME):
            span.set_attributes(
                {
                    "private_search.selected_resources": json_dumps(
                        [
                            r.model_dump(exclude_none=True, mode="json")
                            for r in tool.resources or []
                        ]
                    ),
                }
            )
            if not tool.resources or all(
                r.type == PrivateSearchResourceType.FOLDER for r in tool.resources
            ):
                func = tool_executor_config[cls.PRIVATE_SEARCH_TOOL_NAME]["func"]
                retrievals: list[ResourceChunkRetrieval] = await func(
                    message.message["content"]
                )
                related_resources: list[Resource] = []
                for r in retrievals:
                    if r.chunk.resource_id not in [res.id for res in related_resources]:
                        related_resources.append(
                            Resource.model_validate(
                                {
                                    "id": r.chunk.resource_id,
                                    "name": r.chunk.title,
                                    "type": r.type,
                                }
                            )
                        )
                tool.related_resources = related_resources
                span.set_attributes(
                    {
                        "related_resources": json_dumps(
                            [r.model_dump(exclude_none=True) for r in related_resources]
                        )
                    }
                )
        return message

    @classmethod
    def parse_selected_resources(
        cls,
        options: ChatRequestOptions,
    ) -> list[str]:
        tools = ToolDict(options.tools or [])
        if tool := tools.get(cls.PRIVATE_SEARCH_TOOL_NAME):
            if tool.resources:
                all_folders = all(
                    resource.type == PrivateSearchResourceType.FOLDER
                    for resource in tool.resources
                )

                selected_section = "\n".join(
                    [
                        "<selected_private_resources>",
                        json_dumps(
                            [
                                {"title": resource.name or None, "type": resource.type}
                                for resource in tool.resources
                            ]
                        ),
                        "</selected_private_resources>",
                    ]
                )

                if all_folders and tool.related_resources:
                    related_resources_data = [
                        {"title": resource.name or None, "type": resource.type}
                        for resource in tool.related_resources
                    ]

                    suggested_section = "\n".join(
                        [
                            "<system_suggested_private_resources>",
                            json_dumps(related_resources_data),
                            "</system_suggested_private_resources>",
                        ]
                    )

                    return [selected_section + "\n\n" + suggested_section]
                else:
                    return [selected_section]
            elif tool.related_resources:
                return [
                    "\n".join(
                        [
                            "<system_suggested_private_resources>",
                            json_dumps(
                                [
                                    {
                                        "title": resource.name or None,
                                        "type": resource.type,
                                    }
                                    for resource in tool.related_resources
                                ]
                            ),
                            "</system_suggested_private_resources>",
                        ]
                    )
                ]
        return []

    @classmethod
    def parse_selected_tools(cls, attrs: MessageAttrs) -> list[str]:
        tools = [tool.name for tool in attrs.tools or []]

        # if private_search is selected，resource tools are automatically available
        if "private_search" in tools:
            tools = tools + [t for t in RESOURCE_TOOLS if t not in tools]

        return [
            "\n".join(
                [
                    "<selected_tools>",
                    json_dumps(
                        {
                            "selected": tools,
                            "disabled": [t for t in ALL_TOOLS if t not in tools],
                        }
                    ),
                    "</selected_tools>",
                ]
            )
        ]

    @classmethod
    def parse_visible_resources(
        cls, options: ChatRequestOptions, original_tools: list | None = None
    ) -> list[str]:
        """Parse visible_resources from resource tools and format for LLM context.

        This provides the LLM with a list of available resources and their short IDs,
        so it knows what folders/documents exist and can use the appropriate tools.

        Args:
            options: The chat request options (may have serialized tools without visible_resources)
            original_tools: Original tools list with visible_resources populated (optional)
        """
        # Use original_tools if provided (contains visible_resources), otherwise fall back to options.tools
        tools_list = original_tools if original_tools is not None else (options.tools or [])
        tools = ToolDict(tools_list)

        # Find a tool that has visible_resources
        # First check resource tools, then check private_search (which also has visible_resources)
        resource_tool: BaseResourceTool | None = None

        # Check resource tools first
        for tool_name in RESOURCE_TOOLS:
            if tool := tools.get(tool_name):
                if isinstance(tool, BaseResourceTool) and tool.visible_resources:
                    resource_tool = tool
                    break

        # If not found, check private_search (visible_resources is defined there)
        if not resource_tool:
            if tool := tools.get("private_search"):
                if hasattr(tool, "visible_resources") and tool.visible_resources:
                    resource_tool = tool

        if not resource_tool:
            return []
        # Get resources with short IDs
        # PrivateSearchTool doesn't have get_resources_with_short_ids(), so handle it manually
        if hasattr(resource_tool, "get_resources_with_short_ids"):
            resources_with_ids = resource_tool.get_resources_with_short_ids()
        else:
            # Manually generate short IDs for PrivateSearchTool
            resources_with_ids = []
            resource_counter = 0
            folder_counter = 0
            for resource in resource_tool.visible_resources:
                if resource.type == PrivateSearchResourceType.FOLDER:
                    folder_counter += 1
                    short_id = f"f{folder_counter}"
                else:
                    resource_counter += 1
                    short_id = f"r{resource_counter}"
                resources_with_ids.append({
                    "short_id": short_id,
                    "id": resource.id,
                    "name": resource.name,
                    "type": resource.type.value,
                })

        if not resources_with_ids:
            return []

        # Separate folders and documents for clarity
        folders = [r for r in resources_with_ids if r["type"] == "folder"]
        documents = [r for r in resources_with_ids if r["type"] == "resource"]

        # Format for LLM with clear guidance
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
            "- To see folder contents: get_children(folder_short_id) e.g., get_children('f1')",
            "- To read document content: get_resources([doc_short_ids]) e.g., get_resources(['r1', 'r2'])",
            "- For time-based queries ('recent', 'this week'): use filter_by_time",
            "- For tag-based queries: use filter_by_tag",
            "- private_search is for keyword search across all documents",
            "</available_resources>",
        ])

        return ["\n".join(lines)]

    @classmethod
    def parse_user_query(
        cls,
        query: str,
        attrs: MessageAttrs,
        # original_tools: list | None = None,
    ) -> str:
        return remove_continuous_break_lines(
            "\n\n".join(
                [
                    "\n".join(["<query>", query, "</query>"]),
                    *cls.parse_selected_resources(attrs),
                    # *cls.parse_visible_resources(attrs, original_tools=original_tools),
                    *cls.parse_selected_tools(attrs),
                ]
            )
        )

    @classmethod
    def parse_message(cls, message: MessageDto) -> dict:
        openai_message: dict = message.message
        if openai_message["role"] == "user" and message.attrs:
            return openai_message | {
                "content": cls.parse_user_query(
                    message.message["content"], message.attrs
                )
            }
        return openai_message

    @classmethod
    def parse_context(
        cls, attrs: MessageAttrs,
        #original_tools: list | None = None
    ) -> str:
        return remove_continuous_break_lines(
            "\n\n".join(
                [
                    *cls.parse_selected_resources(attrs),
                    # *cls.parse_visible_resources(attrs, original_tools=original_tools),
                    *cls.parse_selected_tools(attrs),
                ]
            )
        )

    @classmethod
    def message_dtos_to_openai_messages(
        cls, dtos: list[MessageDto], original_tools: list | None = None
    ) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []

        # 找到最后一个 user message 的索引
        last_user_idx = -1
        for i, dto in enumerate(dtos):
            if dto.message["role"] == "user":
                last_user_idx = i

        for i, dto in enumerate(dtos):
            messages.append(dto.message)
            # 只对最后一个 user message 添加 context
            if i == last_user_idx and dto.message["role"] == "user" and dto.attrs:
                messages.append(
                    {
                        "role": "system",
                        "content": cls.parse_context(
                            dto.attrs #, original_tools=original_tools
                        ),
                    }
                )

        return messages


class BaseSearchableAgent(BaseStreamable, ABC):
    def __init__(self, config: Config):
        # Search tools (existing)
        self.knowledge_database_retriever = MeiliVectorRetriever(config=config.vector)
        self.web_search_retriever = SearXNG(
            base_url=config.tools.searxng.base_url, engines=config.tools.searxng.engines
        )

        self.reranker: Reranker = Reranker(config.tools.reranker)

        self.retriever_mapping: dict[str, BaseRetriever] = {
            each.name: each
            for each in [self.knowledge_database_retriever, self.web_search_retriever]
        }

        # Resource tools (new)
        self.resource_api_client = ResourceAPIClient(config.tools.resource_api)
        self.resource_handlers: dict[str, BaseResourceHandler] = {
            "get_resources": GetResourcesHandler(self.resource_api_client),
            "get_children": GetChildrenHandler(self.resource_api_client),
            "get_parent": GetParentHandler(self.resource_api_client),
            "filter_by_time": FilterByTimeHandler(self.resource_api_client),
            "filter_by_tag": FilterByTagHandler(self.resource_api_client),
        }

        # Combine all tool schemas
        self.all_tools: list[dict] = [
            retriever.get_schema() for retriever in self.retriever_mapping.values()
        ] + [handler.get_schema() for handler in self.resource_handlers.values()]

    def get_tool_executor(
        self,
        options: ChatRequestOptions,
        trace_info: TraceInfo,
        wrap_reranker: bool = True,
    ) -> ToolExecutor:
        search_tool_config_list: list[ToolExecutorConfig] = []
        resource_tool_config_list: list[ToolExecutorConfig] = []

        for tool in options.tools or []:
            if tool.name in self.retriever_mapping:
                # Search tools
                config = self.retriever_mapping[tool.name].get_tool_executor_config(
                    tool, trace_info=trace_info.get_child(tool.name)
                )
                search_tool_config_list.append(config)
            elif tool.name in self.resource_handlers:
                # Resource tools
                config = self.resource_handlers[tool.name].get_tool_executor_config(
                    tool, trace_info=trace_info.get_child(tool.name)
                )
                resource_tool_config_list.append(config)

        # Apply reranker only to search tools
        if options.merge_search and search_tool_config_list:
            search_tool_config_list = [
                get_tool_executor_config(search_tool_config_list, self.reranker)
            ]
        elif wrap_reranker:
            for tool_config in search_tool_config_list:
                tool_config["func"] = self.reranker.wrap(
                    func=tool_config["func"],
                    trace_info=trace_info.get_child("reranker"),
                )

        # Combine all tool configs
        all_tool_config_list = search_tool_config_list + resource_tool_config_list
        tool_executor_config: dict = {c["name"]: c for c in all_tool_config_list}
        tool_executor = ToolExecutor(tool_executor_config)
        return tool_executor


class Agent(BaseSearchableAgent):
    def __init__(self, config: Config, system_prompt_template_name: str):
        super().__init__(config)
        self.openai = config.grimoire.openai

        self.template_parser = TemplateParser(
            base_dir=project_root.path("omnibox_wizard/resources/prompt_templates")
        )
        self.system_prompt_template = self.template_parser.get_template(
            system_prompt_template_name
        )

        self.custom_tool_call: bool | None = config.grimoire.custom_tool_call
        self.custom_tool_call = True

    @classmethod
    def has_function(cls, tools: list[dict] | None, function_name: str) -> bool:
        for tool in tools or []:
            if tool.get("function", {}).get("name", {}) == function_name:
                return True
        return False

    @classmethod
    def yield_complete_message(
        cls, message: dict, attrs: dict | None = None
    ) -> Iterable[ChatResponse]:
        yield ChatBOSResponse.model_validate({"role": message["role"]})
        yield ChatDeltaResponse.model_validate(
            {"message": message} | ({"attrs": attrs} if attrs else {})
        )
        yield ChatEOSResponse()

    async def chat(
        self,
        messages: list[dict[str, str]],
        enable_thinking: bool | None = None,
        tools: list[dict] | None = None,
        custom_tool_call: bool = False,
        force_private_search_option: Literal["disable", "enable", "auto"] = "auto",
        *,
        trace_info: TraceInfo | None = None,
    ) -> AsyncIterable[ChatResponse | MessageDto]:
        chunks: list[dict] = []
        with tracer.start_as_current_span("agent.chat") as span:
            assistant_message: dict = {"role": "assistant"}

            force_private_search: bool = (
                (
                    force_private_search_option == "enable"
                    or (force_private_search_option == "auto" and not enable_thinking)
                )
                and len(messages) == 2
                and self.has_function(tools, DEFAULT_TOOL_NAME)
            )
            if force_private_search:
                assert messages[0]["role"] == "system" and messages[1]["role"] == "user"
                assistant_message.setdefault("tool_calls", []).append(
                    {
                        "id": str(uuid4()).replace("-", ""),
                        "type": "function",
                        "function": {
                            "name": DEFAULT_TOOL_NAME,
                            "arguments": json_dumps({"query": messages[1]["content"]}),
                        },
                    }
                )
                for r in self.yield_complete_message(assistant_message):
                    yield r
            else:
                if trace_info:
                    trace_info.debug(
                        {
                            "messages": messages,
                            "enable_thinking": enable_thinking,
                            "tools": tools,
                            "custom_tool_call": custom_tool_call,
                            "force_private_search_option": force_private_search_option,
                        }
                    )

                kwargs: dict = {}
                openai = self.openai.get_config("large", default=self.openai.default)
                if enable_thinking is not None:
                    if large_thinking := self.openai.get_config(
                        "large", thinking=True, default=None
                    ):
                        if enable_thinking:
                            openai = large_thinking
                    else:
                        kwargs["extra_body"] = {"enable_thinking": enable_thinking}
                if tools and not custom_tool_call:
                    kwargs["tools"] = tools

                with tracer.start_as_current_span("agent.chat.openai") as openai_span:
                    start_time: float = time.time()
                    ttft: float = -1.0

                    headers = {}
                    propagate.inject(headers)
                    if trace_info:
                        headers = headers | {"X-Request-Id": trace_info.request_id}

                    openai_response: AsyncStream[
                        ChatCompletionChunk
                    ] = await openai.chat(
                        messages=messages,
                        stream=True,
                        extra_headers=headers if headers else None,
                        **kwargs,
                    )

                    yield ChatBOSResponse(role="assistant")
                    tool_calls_buffer: str = ""
                    stream_parser: StreamParser = StreamParser()

                    async for chunk in openai_response:
                        delta = chunk.choices[0].delta
                        chunks.append(chunk.model_dump(exclude_none=True))
                        if ttft < 0:
                            ttft = time.time() - start_time
                            openai_span.set_attribute("ttft", ttft)

                        if delta.tool_calls:
                            tool_call: ChoiceDeltaToolCall = delta.tool_calls[0]
                            if tool_call.index + 1 > len(
                                assistant_message.get("tool_calls", [])
                            ):
                                assistant_message.setdefault("tool_calls", []).append(
                                    {}
                                )
                            if tool_call.id:
                                assistant_message["tool_calls"][tool_call.index][
                                    "id"
                                ] = tool_call.id
                            if tool_call.type:
                                assistant_message["tool_calls"][tool_call.index][
                                    "type"
                                ] = tool_call.type
                            if tool_call.function:
                                function = tool_call.function
                                function_dict: dict = assistant_message["tool_calls"][
                                    tool_call.index
                                ].setdefault("function", {})
                                if function.name:
                                    function_dict["name"] = (
                                        function_dict.get("name", "") + function.name
                                    )
                                if function.arguments:
                                    function_dict["arguments"] = (
                                        function_dict.get("arguments", "")
                                        + function.arguments
                                    )

                        for key in ["content", "reasoning_content"]:
                            if hasattr(delta, key) and (v := getattr(delta, key)):
                                if custom_tool_call and key == "content":
                                    normal_content: str = ""
                                    operations: list[DeltaOperation] = (
                                        stream_parser.parse(v)
                                    )
                                    for operation in operations:
                                        if operation["tag"] == "think":
                                            raise ValueError(
                                                "Unexpected think operation in content delta."
                                            )
                                        elif operation["tag"] == "tool_call":
                                            tool_calls_buffer += operation["delta"]
                                        else:
                                            normal_content += operation["delta"]
                                    if normal_content:
                                        assistant_message[key] = (
                                            assistant_message.get(key, "")
                                            + normal_content
                                        )
                                        yield ChatDeltaResponse.model_validate(
                                            {"message": {key: normal_content}}
                                        )
                                else:
                                    assistant_message[key] = (
                                        assistant_message.get(key, "") + v
                                    )
                                    yield ChatDeltaResponse.model_validate(
                                        {"message": {key: v}}
                                    )

                if tool_calls_buffer:
                    for line in tool_calls_buffer.splitlines():
                        if json_str := line.strip():
                            try:
                                tool_call_json: dict = jsonlib.loads(json_str)
                                tool_call_json["arguments"] = json_dumps(
                                    tool_call_json["arguments"]
                                )
                                assistant_message.setdefault("tool_calls", []).append(
                                    {
                                        "id": str(uuid4()).replace("-", ""),
                                        "type": "function",
                                        "function": tool_call_json,
                                    }
                                )
                            except jsonlib.JSONDecodeError:
                                continue
                if tool_calls := assistant_message.get("tool_calls"):
                    yield ChatDeltaResponse.model_validate(
                        {"message": {"tool_calls": tool_calls}}
                    )

                yield ChatEOSResponse()
                span.set_attributes(
                    {
                        "model": openai.model,
                        "messages": json_dumps(messages),
                        "assistant_message": json_dumps(assistant_message),
                    }
                )
            yield MessageDto.model_validate({"message": assistant_message})

    async def astream(
        self, trace_info: TraceInfo, agent_request: AgentRequest
    ) -> AsyncIterable[ChatResponse]:
        """
        Process the agent request and yield responses as they are generated.

        1. Initialize the tool executor with the tools specified in the agent request.
        2. Prepare the initial messages, including the system prompt if no messages are provided.
        3. Append the user query to the messages.
        4. Continuously chat with the OpenAI API until the assistant's response is complete.
        5. If tool calls are present in the assistant's response, execute them using the tool executor.

        :param trace_info: Trace information for logging and debugging.
        :param agent_request: The request containing the user's query and tools to be used.
        :return: An async iterable of ChatResponse objects.
        """
        with tracer.start_as_current_span("agent.astream") as span:
            span.set_attributes(
                {
                    "conversation_id": agent_request.conversation_id,
                    "agent_request": json_dumps(
                        agent_request.model_dump(
                            exclude_none=True, exclude={"conversation_id"}
                        )
                    ),
                    "all_tools": f"{self.all_tools}",
                    "custom_tool_call": f"{self.custom_tool_call}"
                }
            )
            trace_info.info({"request": agent_request.model_dump(exclude_none=True)})

            tool_executor = self.get_tool_executor(agent_request, trace_info=trace_info)
            messages: list[MessageDto] = agent_request.messages or []

            if not messages:
                all_tools = self.all_tools
                if agent_request.merge_search:
                    all_tools = [
                        BaseRetriever.generate_schema(
                            "search", get_merged_description(all_tools)
                        )
                    ]
                assert all_tools, "all_tools must not be empty"

                if self.custom_tool_call:
                    prompt: str = self.template_parser.render_template(
                        self.system_prompt_template,
                        lang=agent_request.lang or "简体中文",
                        tools="\n".join(json_dumps(tool) for tool in all_tools)
                        if self.custom_tool_call
                        else None,
                        part_1_enabled=True,
                        part_2_enabled=True,
                    )
                    system_message: dict = {"role": "system", "content": prompt}
                    for r in self.yield_complete_message(system_message):
                        yield r
                    messages.append(
                        MessageDto.model_validate({"message": system_message})
                    )
                else:
                    for i in range(2):
                        prompt: str = self.template_parser.render_template(
                            self.system_prompt_template,
                            lang=agent_request.lang or "简体中文",
                            **{f"part_{i + 1}_enabled": True},
                        )
                        system_message: dict = {"role": "system", "content": prompt}
                        for r in self.yield_complete_message(system_message):
                            yield r
                        messages.append(
                            MessageDto.model_validate({"message": system_message})
                        )
            if messages[-1].message["role"] != "user":
                user_message: MessageDto = MessageDto.model_validate(
                    {
                        "message": {"role": "user", "content": agent_request.query},
                        "attrs": agent_request.model_dump(
                            exclude_none=True, mode="json"
                        ),
                    }
                )
                messages.append(user_message)
                for r in self.yield_complete_message(
                    user_message.message, user_message.attrs
                ):
                    yield r
            await UserQueryPreprocessor.with_related_resources_(
                messages[-1], tool_executor.config
            )

            while messages[-1].message["role"] != "assistant":
                async for chunk in self.chat(
                    messages=UserQueryPreprocessor.message_dtos_to_openai_messages(
                        messages, original_tools=agent_request.tools
                    ),
                    enable_thinking=agent_request.enable_thinking,
                    tools=tool_executor.tools,
                    custom_tool_call=self.custom_tool_call,
                    force_private_search_option="disable",
                    trace_info=trace_info,
                ):
                    if isinstance(chunk, MessageDto):
                        messages.append(chunk)
                    elif isinstance(chunk, ChatBaseResponse):
                        yield chunk
                    else:
                        raise ValueError(f"Unexpected chunk type: {type(chunk)}")
                if messages[-1].message.get("tool_calls", []):
                    async for chunk in tool_executor.astream(
                        messages, trace_info=trace_info.get_child("tool_executor")
                    ):
                        if isinstance(chunk, MessageDto):
                            messages.append(chunk)
                        elif isinstance(chunk, ChatBaseResponse):
                            yield chunk
                        else:
                            raise ValueError(f"Unexpected chunk type: {type(chunk)}")
