import json as jsonlib
from datetime import datetime
from typing import AsyncIterable, Literal, Iterable
from uuid import uuid4

from openai import AsyncOpenAI, AsyncStream, NOT_GIVEN
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

from src.common import project_root
from src.common.template_render import render_template
from src.common.trace_info import TraceInfo
from src.common.utils import remove_continuous_break_lines
from src.wizard.config import OpenAIConfig, ToolsConfig, VectorConfig
from src.wizard.grimoire.agent.tool_executor import ToolExecutor
from src.wizard.grimoire.base_streamable import BaseStreamable, ChatResponse
from src.wizard.grimoire.entity.api import (
    ChatDeltaResponse, AgentRequest, ChatBOSResponse, ChatEOSResponse, MessageDto, ChatOptions, ChatBaseResponse
)
from src.wizard.grimoire.entity.tools import ToolExecutorConfig
from src.wizard.grimoire.retriever.base import BaseRetriever
from src.wizard.grimoire.retriever.meili_vector_db import MeiliVectorRetriever
from src.wizard.grimoire.retriever.reranker import get_tool_executor_config
from src.wizard.grimoire.retriever.searxng import SearXNG

DEFAULT_TOOL_NAME: str = "private_search"


class Agent(BaseStreamable):
    def __init__(
            self,
            openai_config: OpenAIConfig,
            tools_config: ToolsConfig,
            vector_config: VectorConfig,
            system_prompt_template_path: str,
            reranker_config: OpenAIConfig | None = None,
    ):
        self.client = AsyncOpenAI(api_key=openai_config.api_key, base_url=openai_config.base_url)
        self.model = openai_config.model

        self.reranker_config: OpenAIConfig | None = reranker_config

        with project_root.open(system_prompt_template_path) as f:
            self.system_prompt = f.read()

        self.web_search_retriever = SearXNG(base_url=tools_config.searxng_base_url)
        self.knowledge_database_retriever = MeiliVectorRetriever(config=vector_config)

        self.retriever_mapping: dict[str, BaseRetriever] = {
            each.name: each
            for each in [self.web_search_retriever, self.knowledge_database_retriever]
        }

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
            message_dtos: list[MessageDto],
            enable_thinking: bool | None = None,
            tools: list[dict] | None = None,
            custom_tool_call: bool = False,
            force_private_search_option: Literal["disable", "enable", "auto"] = "auto"
    ) -> AsyncIterable[ChatResponse | dict]:
        messages = list(map(self.parse_message, message_dtos))

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
                    "arguments": jsonlib.dumps(
                        {"query": messages[1]['content']}, ensure_ascii=False, separators=(",", ":")
                    )
                }
            })
            for r in self.yield_complete_message(assistant_message):
                yield r
        else:
            if custom_tool_call and len(messages) == 2:
                messages[0]['content'] += """\n\n# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{{tools}}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{"name": <function-name>, "arguments": <args-json-object>}
</tool_call>""".replace("{{tools}}", "\n".join([jsonlib.dumps(tool, ensure_ascii=False) for tool in tools or []]))
            openai_response: AsyncStream[ChatCompletionChunk] = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools if tools and not custom_tool_call else NOT_GIVEN,
                stream=True,
                **({"extra_body": {"enable_thinking": enable_thinking}} if enable_thinking is not None else {})
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
                            tool_call_json['arguments'] = jsonlib.dumps(
                                tool_call_json['arguments'], ensure_ascii=False, separators=(",", ":")
                            )
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

    @classmethod
    def parse_selected_resources(cls, options: ChatOptions) -> str:
        for tool in options.tools or []:
            if tool.name == "private_search":
                if tool.resources:
                    resources = [
                        resource.model_dump(include={"name", "type"}, exclude_none=True)
                        for resource in tool.resources
                    ]
                    return "# Selected private resources\n\n```json\n" + jsonlib.dumps(
                        resources, ensure_ascii=False, separators=(",", ":")
                    ) + "\n```"
        return ""

    @classmethod
    def parse_selected_tools(cls, options: ChatOptions) -> str:
        if not options.tools:
            return ""
        tools = [tool.name for tool in options.tools]
        return "# Selected tools\n\n```json\n" + jsonlib.dumps(
            tools, ensure_ascii=False, separators=(",", ":")
        ) + "\n```"

    @classmethod
    def parse_user_query(cls, query: str, options: ChatOptions) -> str:
        return remove_continuous_break_lines("\n\n".join([
            "# Query",
            query,
            cls.parse_selected_resources(options),
            cls.parse_selected_tools(options),
        ]))

    @classmethod
    def parse_message(cls, message: MessageDto) -> dict:
        openai_message: dict = message.message
        if openai_message['role'] == 'user' and message.attrs:
            return openai_message | {"content": cls.parse_user_query(message.message["content"], message.attrs)}
        return openai_message

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
        tool_executor_config_list: list[ToolExecutorConfig] = [
            self.retriever_mapping[tool.name].get_tool_executor_config(tool, trace_info=trace_info)
            for tool in agent_request.tools or []
        ]

        if agent_request.merge_search:
            tool_executor_config_list = [get_tool_executor_config(tool_executor_config_list, self.reranker_config)]

        tool_executor = ToolExecutor({c["name"]: c for c in tool_executor_config_list})

        messages: list[MessageDto] = agent_request.messages or []

        if not messages:
            prompt: str = render_template(self.system_prompt, {
                "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "lang": agent_request.lang or "简体中文",
            }).strip()
            system_message: dict = {"role": "system", "content": prompt}
            for r in self.yield_complete_message(system_message):
                yield r
            messages.append(MessageDto.model_validate({"message": system_message}))

        user_message: MessageDto = MessageDto.model_validate({
            "message": {"role": "user", "content": agent_request.query},
            "attrs": agent_request.model_dump(
                exclude_none=True,
                include={"enable_thinking", "merge_search", "tools"}
            ),
        })
        messages.append(user_message)
        for r in self.yield_complete_message(user_message.message, user_message.attrs):
            yield r

        while messages[-1].message['role'] != 'assistant':
            async for chunk in self.chat(
                    messages,
                    enable_thinking=agent_request.enable_thinking,
                    tools=tool_executor.tools,
                    custom_tool_call=False,
                    force_private_search_option="disable"
            ):
                if isinstance(chunk, MessageDto):
                    messages.append(chunk)
                elif isinstance(chunk, ChatBaseResponse):
                    yield chunk
                else:
                    raise ValueError(f"Unexpected chunk type: {type(chunk)}")
            if messages[-1].message.get('tool_calls', []):
                async for chunk in tool_executor.astream(messages):
                    if isinstance(chunk, MessageDto):
                        messages.append(chunk)
                    elif isinstance(chunk, ChatBaseResponse):
                        yield chunk
                    else:
                        raise ValueError(f"Unexpected chunk type: {type(chunk)}")
