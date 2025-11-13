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
from omnibox_wizard.wizard.grimoire.agent.stream_parser import StreamParser, DeltaOperation
from omnibox_wizard.wizard.grimoire.agent.tool_executor import ToolExecutor
from omnibox_wizard.wizard.grimoire.base_streamable import BaseStreamable, ChatResponse
from omnibox_wizard.wizard.grimoire.entity.api import (
    ChatDeltaResponse, AgentRequest, ChatBOSResponse, ChatEOSResponse, MessageDto,
    ChatRequestOptions, ChatBaseResponse, MessageAttrs
)
from omnibox_wizard.wizard.grimoire.entity.chunk import ResourceChunkRetrieval
from omnibox_wizard.wizard.grimoire.entity.tools import (
    ToolExecutorConfig, ToolDict, Resource, ALL_TOOLS, PrivateSearchResourceType
)
from omnibox_wizard.wizard.grimoire.retriever.base import BaseRetriever
from omnibox_wizard.wizard.grimoire.retriever.meili_vector_db import MeiliVectorRetriever
from omnibox_wizard.wizard.grimoire.retriever.reranker import get_tool_executor_config, get_merged_description, Reranker
from omnibox_wizard.wizard.grimoire.retriever.searxng import SearXNG

DEFAULT_TOOL_NAME: str = "private_search"
json_dumps = partial(jsonlib.dumps, ensure_ascii=False, separators=(",", ":"))
tracer = trace.get_tracer(__name__)


class UserQueryPreprocessor:
    PRIVATE_SEARCH_TOOL_NAME: str = "private_search"

    @classmethod
    @tracer.start_as_current_span("UserQueryPreprocessor.with_related_resources_")
    async def with_related_resources_(
            cls,
            message: MessageDto,
            tool_executor_config: dict[str, ToolExecutorConfig]
    ) -> MessageDto:
        tools = ToolDict(message.attrs.tools or [])
        span = trace.get_current_span()
        span.set_attribute("tool_names", json_dumps([tool.name for tool in message.attrs.tools or []]))
        if tool := tools.get(cls.PRIVATE_SEARCH_TOOL_NAME):
            span.set_attributes({
                "private_search.selected_resources": json_dumps([
                    r.model_dump(exclude_none=True, mode="json") for r in tool.resources or []]),
            })
            if not tool.resources or all(r.type == PrivateSearchResourceType.FOLDER for r in tool.resources):
                func = tool_executor_config[cls.PRIVATE_SEARCH_TOOL_NAME]["func"]
                retrievals: list[ResourceChunkRetrieval] = await func(message.message["content"])
                related_resources: list[Resource] = []
                for r in retrievals:
                    if r.chunk.resource_id not in [res.id for res in related_resources]:
                        related_resources.append(Resource.model_validate({
                            "id": r.chunk.resource_id,
                            "name": r.chunk.title,
                            "type": r.type,
                        }))
                tool.related_resources = related_resources
                span.set_attributes({
                    "related_resources": json_dumps([r.model_dump(exclude_none=True) for r in related_resources])
                })
        return message

    @classmethod
    def parse_selected_resources(
            cls,
            options: ChatRequestOptions,
    ) -> list[str]:
        tools = ToolDict(options.tools or [])
        if tool := tools.get(cls.PRIVATE_SEARCH_TOOL_NAME):
            if tool.resources:
                all_folders = all(resource.type == PrivateSearchResourceType.FOLDER for resource in tool.resources)

                selected_section = "\n".join([
                    "<selected_private_resources>",
                    json_dumps(
                        [{"title": resource.name or None, "type": resource.type} for resource in tool.resources]),
                    "</selected_private_resources>"
                ])

                if all_folders and tool.related_resources:
                    related_resources_data = [{"title": resource.name or None, "type": resource.type} for resource in
                                              tool.related_resources]

                    suggested_section = "\n".join([
                        "<system_suggested_private_resources>",
                        json_dumps(related_resources_data),
                        "</system_suggested_private_resources>"
                    ])

                    return [selected_section + "\n\n" + suggested_section]
                else:
                    return [selected_section]
            elif tool.related_resources:
                return [
                    "\n".join([
                        "<system_suggested_private_resources>",
                        json_dumps([{"title": resource.name or None, "type": resource.type} for resource in
                                    tool.related_resources]),
                        "</system_suggested_private_resources>"
                    ])
                ]
        return []

    @classmethod
    def parse_selected_tools(cls, attrs: MessageAttrs) -> list[str]:
        tools = [tool.name for tool in attrs.tools or []]
        return [
            "\n".join([
                "<selected_tools>",
                json_dumps({
                    "selected": tools,
                    "disabled": [t for t in ALL_TOOLS if t not in tools],
                }),
                "</selected_tools>"
            ])
        ]

    @classmethod
    def parse_user_query(
            cls,
            query: str,
            attrs: MessageAttrs,
    ) -> str:
        return remove_continuous_break_lines("\n\n".join([
            "\n".join(["<query>", query, "</query>"]),
            *cls.parse_selected_resources(attrs),
            *cls.parse_selected_tools(attrs),
        ]))

    @classmethod
    def parse_message(cls, message: MessageDto) -> dict:
        openai_message: dict = message.message
        if openai_message['role'] == 'user' and message.attrs:
            return openai_message | {
                "content": cls.parse_user_query(message.message["content"], message.attrs)
            }
        return openai_message

    @classmethod
    def parse_context(cls, attrs: MessageAttrs) -> str:
        return remove_continuous_break_lines("\n\n".join([
            *cls.parse_selected_resources(attrs),
            *cls.parse_selected_tools(attrs),
        ]))

    @classmethod
    def message_dtos_to_openai_messages(cls, dtos: list[MessageDto]) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []

        for dto in dtos:
            messages.append(dto.message)
            if dto.message['role'] == 'user' and dto.attrs:
                messages.append({"role": "system", "content": cls.parse_context(dto.attrs)})

        return messages


class BaseSearchableAgent(BaseStreamable, ABC):
    def __init__(self, config: Config):
        self.knowledge_database_retriever = MeiliVectorRetriever(config=config.vector)
        self.web_search_retriever = SearXNG(
            base_url=config.tools.searxng.base_url, engines=config.tools.searxng.engines
        )

        self.reranker: Reranker | None = Reranker(config.tools.reranker) if config.tools.reranker else None

        self.retriever_mapping: dict[str, BaseRetriever] = {
            each.name: each
            for each in [self.knowledge_database_retriever, self.web_search_retriever]
        }

        self.all_tools: list[dict] = [retriever.get_schema() for retriever in self.retriever_mapping.values()]
        assert all(t in self.retriever_mapping for t in ALL_TOOLS), "All tools must be registered in retriever mapping."

    def get_tool_executor(
            self, options: ChatRequestOptions,
            trace_info: TraceInfo,
            wrap_reranker: bool = True
    ) -> ToolExecutor:
        tool_executor_config_list: list[ToolExecutorConfig] = [
            self.retriever_mapping[tool.name].get_tool_executor_config(tool, trace_info=trace_info.get_child(tool.name))
            for tool in options.tools or []
        ]

        if options.merge_search:
            tool_executor_config_list = [get_tool_executor_config(tool_executor_config_list, self.reranker)]
        elif self.reranker and wrap_reranker:  # Add rerank to tool executor config if reranker_config is provided
            for tool_executor_config in tool_executor_config_list:
                tool_executor_config["func"] = self.reranker.wrap(
                    func=tool_executor_config["func"],
                    trace_info=trace_info.get_child("reranker")
                )

        tool_executor_config: dict = {c["name"]: c for c in tool_executor_config_list}
        tool_executor = ToolExecutor(tool_executor_config)
        return tool_executor


class Agent(BaseSearchableAgent):
    def __init__(self, config: Config, system_prompt_template_name: str):
        super().__init__(config)
        self.openai = config.grimoire.openai

        self.template_parser = TemplateParser(base_dir=project_root.path("omnibox_wizard/resources/prompt_templates"))
        self.system_prompt_template = self.template_parser.get_template(system_prompt_template_name)

        self.custom_tool_call: bool | None = config.grimoire.custom_tool_call

    @classmethod
    def has_function(cls, tools: list[dict] | None, function_name: str) -> bool:
        for tool in tools or []:
            if tool.get("function", {}).get("name", {}) == function_name:
                return True
        return False

    @classmethod
    def yield_complete_message(cls, message: dict, attrs: dict | None = None) -> Iterable[ChatResponse]:
        yield ChatBOSResponse.model_validate({"role": message["role"]})
        yield ChatDeltaResponse.model_validate({"message": message} | ({"attrs": attrs} if attrs else {}))
        yield ChatEOSResponse()

    async def chat(
            self,
            messages: list[dict[str, str]],
            enable_thinking: bool | None = None,
            tools: list[dict] | None = None,
            custom_tool_call: bool = False,
            force_private_search_option: Literal["disable", "enable", "auto"] = "auto",
            *,
            trace_info: TraceInfo | None = None
    ) -> AsyncIterable[ChatResponse | MessageDto]:
        chunks: list[dict] = []
        with tracer.start_as_current_span("agent.chat") as span:
            assistant_message: dict = {'role': 'assistant'}

            force_private_search: bool = (force_private_search_option == "enable" or (
                    force_private_search_option == "auto" and not enable_thinking)) and len(
                messages) == 2 and self.has_function(tools, DEFAULT_TOOL_NAME)
            if force_private_search:
                assert messages[0]['role'] == 'system' and messages[1]['role'] == 'user'
                assistant_message.setdefault('tool_calls', []).append({
                    "id": str(uuid4()).replace('-', ''),
                    "type": "function",
                    "function": {
                        "name": DEFAULT_TOOL_NAME,
                        "arguments": json_dumps({"query": messages[1]['content']})
                    }
                })
                for r in self.yield_complete_message(assistant_message):
                    yield r
            else:
                if trace_info:
                    trace_info.debug({
                        "messages": messages,
                        "enable_thinking": enable_thinking,
                        "tools": tools,
                        "custom_tool_call": custom_tool_call,
                        "force_private_search_option": force_private_search_option
                    })

                kwargs: dict = {}
                openai = self.openai.get_config("large", default=self.openai.default)
                if enable_thinking is not None:
                    if large_thinking := self.openai.get_config("large", thinking=True, default=None):
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

                    openai_response: AsyncStream[ChatCompletionChunk] = await openai.chat(
                        messages=messages,
                        stream=True,
                        extra_headers=headers if headers else None,
                        **kwargs
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
                            if tool_call.index + 1 > len(assistant_message.get('tool_calls', [])):
                                assistant_message.setdefault('tool_calls', []).append({})
                            if tool_call.id:
                                assistant_message['tool_calls'][tool_call.index]['id'] = tool_call.id
                            if tool_call.type:
                                assistant_message['tool_calls'][tool_call.index]['type'] = tool_call.type
                            if tool_call.function:
                                function = tool_call.function
                                function_dict: dict = assistant_message['tool_calls'][tool_call.index].setdefault(
                                    'function',
                                    {})
                                if function.name:
                                    function_dict['name'] = function_dict.get('name', '') + function.name
                                if function.arguments:
                                    function_dict['arguments'] = function_dict.get('arguments', '') + function.arguments

                        for key in ['content', 'reasoning_content']:
                            if hasattr(delta, key) and (v := getattr(delta, key)):
                                if custom_tool_call and key == 'content':
                                    normal_content: str = ''
                                    operations: list[DeltaOperation] = stream_parser.parse(v)
                                    for operation in operations:
                                        if operation['tag'] == 'think':
                                            raise ValueError('Unexpected think operation in content delta.')
                                        elif operation['tag'] == 'tool_call':
                                            tool_calls_buffer += operation['delta']
                                        else:
                                            normal_content += operation['delta']
                                    if normal_content:
                                        assistant_message[key] = assistant_message.get(key, '') + normal_content
                                        yield ChatDeltaResponse.model_validate({"message": {key: normal_content}})
                                else:
                                    assistant_message[key] = assistant_message.get(key, '') + v
                                    yield ChatDeltaResponse.model_validate({"message": {key: v}})

                if tool_calls_buffer:
                    for line in tool_calls_buffer.splitlines():
                        if json_str := line.strip():
                            try:
                                tool_call_json: dict = jsonlib.loads(json_str)
                                tool_call_json['arguments'] = json_dumps(tool_call_json['arguments'])
                                assistant_message.setdefault('tool_calls', []).append({
                                    "id": str(uuid4()).replace('-', ''),
                                    "type": "function",
                                    "function": tool_call_json
                                })
                            except jsonlib.JSONDecodeError:
                                continue
                if tool_calls := assistant_message.get('tool_calls'):
                    yield ChatDeltaResponse.model_validate({"message": {"tool_calls": tool_calls}})

                yield ChatEOSResponse()
                span.set_attributes({
                    "model": openai.model,
                    "messages": json_dumps(messages),
                    "assistant_message": json_dumps(assistant_message),
                })
            yield MessageDto.model_validate({"message": assistant_message})

    async def astream(self, trace_info: TraceInfo, agent_request: AgentRequest) -> AsyncIterable[ChatResponse]:
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
            span.set_attributes({
                "conversation_id": agent_request.conversation_id,
                "agent_request": json_dumps(agent_request.model_dump(
                    exclude_none=True, exclude={"conversation_id"}
                )),
            })
            trace_info.info({"request": agent_request.model_dump(exclude_none=True)})

            tool_executor = self.get_tool_executor(agent_request, trace_info=trace_info)
            messages: list[MessageDto] = agent_request.messages or []

            if not messages:
                all_tools = self.all_tools
                if agent_request.merge_search:
                    all_tools = [BaseRetriever.generate_schema("search", get_merged_description(all_tools))]

                assert all_tools, "all_tools must not be empty"

                if self.custom_tool_call:
                    prompt: str = self.template_parser.render_template(
                        self.system_prompt_template,
                        lang=agent_request.lang or "简体中文",
                        tools="\n".join(
                            json_dumps(tool) for tool in all_tools) if self.custom_tool_call else None,
                        part_1_enabled=True,
                        part_2_enabled=True,
                    )
                    system_message: dict = {"role": "system", "content": prompt}
                    for r in self.yield_complete_message(system_message):
                        yield r
                    messages.append(MessageDto.model_validate({"message": system_message}))
                else:
                    for i in range(2):
                        prompt: str = self.template_parser.render_template(
                            self.system_prompt_template,
                            lang=agent_request.lang or "简体中文",
                            **{f"part_{i + 1}_enabled": True}
                        )
                        system_message: dict = {"role": "system", "content": prompt}
                        for r in self.yield_complete_message(system_message):
                            yield r
                        messages.append(MessageDto.model_validate({"message": system_message}))
            if messages[-1].message['role'] != 'user':
                user_message: MessageDto = MessageDto.model_validate({
                    "message": {"role": "user", "content": agent_request.query},
                    "attrs": agent_request.model_dump(exclude_none=True, mode="json"),
                })
                messages.append(user_message)
                for r in self.yield_complete_message(user_message.message, user_message.attrs):
                    yield r
            await UserQueryPreprocessor.with_related_resources_(messages[-1], tool_executor.config)

            while messages[-1].message['role'] != 'assistant':
                async for chunk in self.chat(
                        messages=UserQueryPreprocessor.message_dtos_to_openai_messages(messages),
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
                if messages[-1].message.get('tool_calls', []):
                    async for chunk in tool_executor.astream(messages,
                                                             trace_info=trace_info.get_child("tool_executor")):
                        if isinstance(chunk, MessageDto):
                            messages.append(chunk)
                        elif isinstance(chunk, ChatBaseResponse):
                            yield chunk
                        else:
                            raise ValueError(f"Unexpected chunk type: {type(chunk)}")
