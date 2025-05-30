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
    ChatDeltaResponse, AgentRequest, ChatBosResponse, ChatEosResponse
)
from wizard.grimoire.entity.tools import ToolExecutorConfig
from wizard.grimoire.retriever.searxng import SearXNG
from wizard.grimoire.retriever.vector_db import VectorRetriever


class Agent(BaseStreamable):
    def __init__(self, openai_config: OpenAIConfig, tools_config: ToolsConfig, vector_config: VectorConfig):
        self.client = AsyncOpenAI(api_key=openai_config.api_key, base_url=openai_config.base_url)
        self.model = openai_config.model

        with project_root.open("resources/prompts/system.md") as f:
            self.system_prompt = f.read()

        self.web_search_retriever = SearXNG(base_url=tools_config.searxng_base_url)
        self.knowledge_database_retriever = VectorRetriever(config=vector_config)

        self.func_mapping = {
            "web_search": self.web_search_retriever.search,
            "knowledge_search": partial(self.knowledge_database_retriever.query, k=10)
        }

    @classmethod
    def has_function(cls, tools: list[dict] | None, function_name: str) -> bool:
        for tool in tools:
            if tool.get("function", {}).get("name", {}) == function_name:
                return True
        return False

    @classmethod
    def yieldCompleteMesasge(cls, message: dict):
        yield ChatBosResponse.model_validate({"role": message["role"]})
        yield ChatDeltaResponse.model_validate({"message": message})
        yield ChatEosResponse()

    async def chat(
            self,
            messages: list[dict[str, str]],
            enable_thinking: bool = False,
            tools: list[dict] | None = None,
    ) -> AsyncIterable[ChatResponse]:
        assistant_message: dict = {'role': 'assistant'}

        if len(messages) == 2 and self.has_function(tools, "knowledge_search"):
            assert messages[0]['role'] == 'system' and messages[1]['role'] == 'user'
            assistant_message.setdefault('tool_calls', []).append({
                "id": str(uuid4()).replace('-', ''),
                "type": "function",
                "function": {
                    "name": "knowledge_search",
                    "arguments": jsonlib.dumps(
                        {"query": messages[1]['content']}, ensure_ascii=False, separators=(",", ":")
                    )
                }
            })
            for r in self.yieldCompleteMesasge(assistant_message):
                yield r
        else:
            openai_response: AsyncStream[ChatCompletionChunk] = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=tools or NOT_GIVEN,
                stream=True,
                extra_body={"enable_thinking": enable_thinking}
            )

            yield ChatBosResponse(role="assistant")

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
                        function_dict: dict = assistant_message['tool_calls'][tool_call.index].setdefault('function', {})
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

            yield ChatEosResponse()

    async def astream(self, trace_info: TraceInfo, agent_request: AgentRequest) -> AsyncIterable[ChatResponse]:
        executor_config: dict[str, ToolExecutorConfig] = {
            tool.name: tool.to_executor_config(self.func_mapping[tool.name], trace_info=trace_info.get_child(tool.name))
            for tool in agent_request.tools or []
        }
        tool_executor = ToolExecutor(executor_config)

        messages = agent_request.messages or []

        if not messages:
            prompt: str = self.system_prompt.format_map({
                "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "lang": "简体中文"
            })
            system_message: dict = {"role": "system", "content": prompt}
            messages.append(system_message)
            for r in self.yieldCompleteMesasge(system_message):
                yield r

        user_message: dict = {"role": "user", "content": agent_request.query}
        messages.append(user_message)
        for r in self.yieldCompleteMesasge(user_message):
            yield r

        current_cite_cnt = agent_request.current_cite_cnt

        while messages[-1]['role'] != 'assistant':
            async for chunk in self.chat(
                    messages,
                    enable_thinking=agent_request.enable_thinking,
                    tools=tool_executor.tools
            ):
                if isinstance(chunk, ChatOpenAIMessageResponse):
                    messages.append(chunk.message)
                yield chunk
            if messages[-1].get('tool_calls', []):
                async for chunk in tool_executor.astream(messages, current_cite_cnt):
                    if isinstance(chunk, ChatOpenAIMessageResponse):
                        messages.append(chunk.message)
                        if (attrs := chunk.attrs) and attrs.citations:
                            current_cite_cnt += len(attrs.citations)
                    yield chunk
