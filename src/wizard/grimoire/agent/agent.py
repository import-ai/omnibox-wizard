import json as jsonlib
from functools import partial
from typing import AsyncIterable, Literal, Iterable
from uuid import uuid4

from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

from src.common.template_parser import get_template, render_template
from src.common.trace_info import TraceInfo
from src.common.utils import remove_continuous_break_lines
from src.wizard.config import OpenAIConfig, Config
from src.wizard.grimoire.agent.tool_executor import ToolExecutor
from src.wizard.grimoire.base_streamable import BaseStreamable, ChatResponse
from src.wizard.grimoire.entity.api import (
    ChatDeltaResponse, AgentRequest, ChatBOSResponse, ChatEOSResponse, MessageDto,
    ChatRequestOptions, ChatBaseResponse, MessageAttrs
)
from src.wizard.grimoire.entity.chunk import ResourceChunkRetrieval
from src.wizard.grimoire.entity.tools import ToolExecutorConfig, ToolDict, Resource
from src.wizard.grimoire.retriever.base import BaseRetriever
from src.wizard.grimoire.retriever.meili_vector_db import MeiliVectorRetriever
from src.wizard.grimoire.retriever.reranker import get_tool_executor_config, get_merged_description, Reranker
from src.wizard.grimoire.retriever.searxng import SearXNG

DEFAULT_TOOL_NAME: str = "private_search"
json_dumps = partial(jsonlib.dumps, ensure_ascii=False, separators=(",", ":"))


class UserQueryPreprocessor:
    PRIVATE_SEARCH_TOOL_NAME: str = "private_search"

    @classmethod
    async def with_related_resources_(
            cls,
            message: MessageDto,
            tool_executor_config: dict[str, ToolExecutorConfig]
    ) -> MessageDto:
        tools = ToolDict(message.attrs.tools or [])
        if (tool := tools.get(cls.PRIVATE_SEARCH_TOOL_NAME)) and not tool.resources:
            func = tool_executor_config[cls.PRIVATE_SEARCH_TOOL_NAME]["func"]
            retrievals: list[ResourceChunkRetrieval] = await func(message.message["content"])
            related_resources: list[Resource] = []
            for r in retrievals:
                if r.chunk.chunk_id not in [res.id for res in related_resources]:
                    related_resources.append(Resource.model_validate({
                        "id": r.chunk.chunk_id,
                        "name": r.chunk.title,
                        "type": r.chunk.type,
                    }))
            tool.related_resources = related_resources
        return message

    @classmethod
    def parse_selected_resources(
            cls,
            options: ChatRequestOptions,
    ) -> list[str]:
        tools = ToolDict(options.tools or [])
        if tool := tools.get(cls.PRIVATE_SEARCH_TOOL_NAME):
            prompt_title = "Selected Private Resources" if tool.resources else "Related Private Resources"
            resources: list[Resource] = tool.resources or tool.related_resources
            if resources:
                return [
                    f"# {prompt_title}",
                    "\n".join([
                        "```json",
                        json_dumps([resource.model_dump(include={"name", "type"}, exclude_none=True) for resource in
                                    resources]),
                        "```"
                    ])
                ]
        return []

    @classmethod
    def parse_selected_tools(cls, attrs: MessageAttrs) -> list[str]:
        if not attrs.tools:
            return []
        tools = [tool.name for tool in attrs.tools]
        return [
            "# Selected Tools",
            "\n".join([
                "```json",
                json_dumps(tools),
                "```"
            ])
        ]

    @classmethod
    def parse_user_query(
            cls,
            query: str,
            attrs: MessageAttrs,
    ) -> str:
        return remove_continuous_break_lines("\n\n".join([
            "# Query",
            query,
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


class Agent(BaseStreamable):
    def __init__(self, config: Config, system_prompt_template_name: str):
        openai_config: OpenAIConfig = config.grimoire.openai["large"]

        self.client = AsyncOpenAI(api_key=openai_config.api_key, base_url=openai_config.base_url)
        self.model = openai_config.model

        self.reranker_model_config: OpenAIConfig | None = config.tools.reranker

        self.system_prompt_template = get_template(system_prompt_template_name)

        self.knowledge_database_retriever = MeiliVectorRetriever(config=config.vector)
        self.web_search_retriever = SearXNG(base_url=config.tools.searxng_base_url)

        self.retriever_mapping: dict[str, BaseRetriever] = {
            each.name: each
            for each in [self.knowledge_database_retriever, self.web_search_retriever]
        }

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
    ) -> AsyncIterable[ChatResponse | dict]:
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
            openai_response: AsyncStream[ChatCompletionChunk] = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=True,
                **((
                       {
                           "extra_body": {"enable_thinking": enable_thinking}
                       } if enable_thinking is not None else {}
                   ) | (
                       {
                           "tools": tools
                       } if (tools and not custom_tool_call) else {}
                   ))
            )

            yield ChatBOSResponse(role="assistant")

            tool_calls_buffer: str = ''
            bot: str = '<tool_call>'
            eot: str = '</tool_call>'
            during_tool_call: bool = False

            async for chunk in openai_response:
                delta = chunk.choices[0].delta

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
                        function_dict: dict = assistant_message['tool_calls'][tool_call.index].setdefault('function',
                                                                                                          {})
                        if function.name:
                            function_dict['name'] = function_dict.get('name', '') + function.name
                        if function.arguments:
                            function_dict['arguments'] = function_dict.get('arguments', '') + function.arguments

                for key in ['content', 'reasoning_content']:
                    if hasattr(delta, key) and (v := getattr(delta, key)):
                        if key == 'content':
                            normal_content: str = v
                            if bot in normal_content:
                                during_tool_call = True
                                normal_content, tool_call_delta = v.split(bot, 1)
                                tool_calls_buffer += tool_call_delta
                            elif during_tool_call:
                                if eot in normal_content:
                                    during_tool_call = False
                                    tool_call_delta, normal_content = v.split(eot, 1)
                                    tool_calls_buffer += tool_call_delta
                                else:
                                    tool_calls_buffer += normal_content
                                    normal_content = ''
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
        all_tools: list[dict] = [retriever.get_schema() for retriever in self.retriever_mapping.values()]
        if all_tools and agent_request.merge_search:
            all_tools = [BaseRetriever.generate_schema("search", get_merged_description(all_tools))]

        tool_executor_config_list: list[ToolExecutorConfig] = [
            self.retriever_mapping[tool.name].get_tool_executor_config(tool, trace_info=trace_info)
            for tool in agent_request.tools or []
        ]

        if agent_request.merge_search:
            tool_executor_config_list = [
                get_tool_executor_config(tool_executor_config_list, self.reranker_model_config)]
        else:  # Add rerank to tool executor config if reranker_config is provided
            if self.reranker_model_config:
                for tool_executor_config in tool_executor_config_list:
                    tool_executor_config["func"] = Reranker(self.reranker_model_config).wrap(
                        func=tool_executor_config["func"],
                        threshold=0.1,
                        k=20,
                        trace_info=trace_info.get_child("reranker")
                    )

        tool_executor_config: dict = {c["name"]: c for c in tool_executor_config_list}
        tool_executor = ToolExecutor(tool_executor_config)

        messages: list[MessageDto] = agent_request.messages or []

        if not messages:
            prompt: str = render_template(
                self.system_prompt_template,
                lang=agent_request.lang or "简体中文",
                tools="\n".join(json_dumps(tool) for tool in all_tools) if self.custom_tool_call and all_tools else None
            )
            system_message: dict = {"role": "system", "content": prompt}
            for r in self.yield_complete_message(system_message):
                yield r
            messages.append(MessageDto.model_validate({"message": system_message}))

        user_message: MessageDto = MessageDto.model_validate({
            "message": {"role": "user", "content": agent_request.query},
            "attrs": agent_request.model_dump(exclude_none=True),
        })
        user_message = await UserQueryPreprocessor.with_related_resources_(user_message, tool_executor_config)

        messages.append(user_message)
        for r in self.yield_complete_message(user_message.message, user_message.attrs):
            yield r

        while messages[-1].message['role'] != 'assistant':
            async for chunk in self.chat(
                    messages=list(map(UserQueryPreprocessor.parse_message, messages)),
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
                async for chunk in tool_executor.astream(messages, trace_info=trace_info.get_child("tool_executor")):
                    if isinstance(chunk, MessageDto):
                        messages.append(chunk)
                    elif isinstance(chunk, ChatBaseResponse):
                        yield chunk
                    else:
                        raise ValueError(f"Unexpected chunk type: {type(chunk)}")
