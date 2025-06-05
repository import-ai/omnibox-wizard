import json as jsonlib
from datetime import datetime
from functools import partial
from typing import AsyncIterable
from uuid import uuid4

from openai import AsyncOpenAI, AsyncStream, NOT_GIVEN
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

from common import project_root
from common.trace_info import TraceInfo
from wizard.config import OpenAIConfig, ToolsConfig, VectorConfig
from wizard.grimoire.agent.tools import ToolExecutor
from wizard.grimoire.base_streamable import BaseStreamable, ChatResponse
from wizard.grimoire.entity.api import (
    ChatDeltaResponse, AgentRequest, ChatBOSResponse, ChatEOSResponse
)
from wizard.grimoire.entity.tools import FunctionMeta, ToolName
from wizard.grimoire.retriever.searxng import SearXNG
from wizard.grimoire.retriever.vector_db import VectorRetriever

DEFAULT_TOOL_NAME: str = "search"


class Agent(BaseStreamable):
    def __init__(
            self,
            openai_config: OpenAIConfig,
            tools_config: ToolsConfig,
            vector_config: VectorConfig,
            reranker_config: OpenAIConfig | None = None
    ):
        self.client = AsyncOpenAI(api_key=openai_config.api_key, base_url=openai_config.base_url)
        self.model = openai_config.model

        self.reranker_config: OpenAIConfig | None = reranker_config

        with project_root.open("resources/prompts/system.md") as f:
            self.system_prompt = f.read()

        self.web_search_retriever = SearXNG(base_url=tools_config.searxng_base_url)
        self.knowledge_database_retriever = VectorRetriever(config=vector_config)

        self.func_mapping: dict[ToolName, FunctionMeta] = {
            "web_search": FunctionMeta(
                name="web_search",
                description="Search the web for public information.",
                func=self.web_search_retriever.search
            ),
            "knowledge_search": FunctionMeta(
                name="knowledge_search",
                description="Search user's personal, private knowledge database.",
                func=partial(self.knowledge_database_retriever.query, k=20)
            )
        }

    @classmethod
    def has_function(cls, tools: list[dict] | None, function_name: str) -> bool:
        for tool in tools:
            if tool.get("function", {}).get("name", {}) == function_name:
                return True
        return False

    @classmethod
    def yield_complete_message(cls, message: dict):
        yield ChatBOSResponse.model_validate({"role": message["role"]})
        yield ChatDeltaResponse.model_validate({"message": message})
        yield ChatEOSResponse()

    async def chat(
            self,
            messages: list[dict[str, str]],
            enable_thinking: bool = False,
            tools: list[dict] | None = None,
    ) -> AsyncIterable[ChatResponse | dict]:
        assistant_message: dict = {'role': 'assistant'}

        if len(messages) == 2 and self.has_function(tools, DEFAULT_TOOL_NAME):
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
            openai_response: AsyncStream[ChatCompletionChunk] = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools or NOT_GIVEN,
                stream=True,
                extra_body={"enable_thinking": enable_thinking}
            )

            yield ChatBOSResponse(role="assistant")

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
                        assistant_message[key] = assistant_message.get(key, '') + v
                        yield ChatDeltaResponse.model_validate({"message": {key: v}})
            if tool_calls := assistant_message.get('tool_calls'):
                yield ChatDeltaResponse.model_validate({"message": {"tool_calls": tool_calls}})

            yield ChatEOSResponse()
        yield assistant_message

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
        tool_executor = ToolExecutor.from_tools(agent_request.tools, self.func_mapping, self.reranker_config)

        messages = agent_request.messages or []

        if not messages:
            prompt: str = self.system_prompt.format_map({
                "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "lang": "简体中文"
            })
            system_message: dict = {"role": "system", "content": prompt}
            messages.append(system_message)
            for r in self.yield_complete_message(system_message):
                yield r

        user_message: dict = {"role": "user", "content": agent_request.query}
        messages.append(user_message)
        for r in self.yield_complete_message(user_message):
            yield r

        current_cite_cnt = agent_request.current_cite_cnt

        while messages[-1]['role'] != 'assistant':
            async for chunk in self.chat(
                    messages,
                    enable_thinking=agent_request.enable_thinking,
                    tools=tool_executor.tools
            ):
                if isinstance(chunk, dict):
                    messages.append(chunk)
                else:
                    yield chunk
            if messages[-1].get('tool_calls', []):
                async for chunk in tool_executor.astream(messages, current_cite_cnt):
                    if isinstance(chunk, ChatDeltaResponse):
                        tool_message: dict = chunk.message.model_dump(exclude_none=True)
                        messages.append({"role": "tool", **tool_message})
                        if (attrs := chunk.attrs) and attrs.citations:
                            current_cite_cnt += len(attrs.citations)
                    yield chunk
