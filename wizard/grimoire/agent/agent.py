import json as jsonlib
from typing import AsyncIterable, TypeVar, Callable

from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletionChunk
from openai.types.chat.chat_completion_chunk import ChoiceDeltaToolCall

from wizard.config import OpenAIConfig
from wizard.grimoire.entity.api import (
    ChatThinkDeltaResponse,
    ChatBaseResponse,
    ChatDeltaResponse,
    AgentRequest, ChatOpenAIMessageResponse
)

Response = TypeVar("Response", bound=ChatBaseResponse)


class Agent:
    def __init__(self, openai_config: OpenAIConfig):
        self.client = AsyncOpenAI(api_key=openai_config.api_key, base_url=openai_config.base_url)
        self.model = openai_config.model

    async def chat(
            self,
            messages: list[dict[str, str]],
            enable_thinking: bool = False,
            tools: list[dict] | None = None,
            tools_mapping: dict[str, Callable] | None = None
    ) -> AsyncIterable[Response]:
        openai_response: AsyncStream[ChatCompletionChunk] = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            stream=True,
            extra_body={"enable_thinking": enable_thinking}
        )
        assistant_message: dict = {'role': 'assistant'}

        messages.append(assistant_message)

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
                    if key == 'reasoning_content':
                        yield ChatThinkDeltaResponse(delta=v)
                    if key == 'content':
                        yield ChatDeltaResponse(delta=v)

        yield ChatOpenAIMessageResponse(message=assistant_message)

        if tool_calls := assistant_message.get('tool_calls', []):
            for tool_call in tool_calls:
                function = tool_call['function']
                function_args = jsonlib.loads(function['arguments'])
                if function['name'] in tools_mapping:
                    result = tools_mapping[function['name']](**function_args)
                else:
                    raise ValueError(f"Unknown function: {function['name']}")
                tool_message = {"role": "tool", "content": jsonlib.dumps(result), "tool_call_id": tool_call['id']}
                messages.append(tool_message)

                yield ChatOpenAIMessageResponse(message=tool_message)

    async def astream(self, agent_request: AgentRequest) -> AsyncIterable[Response]:
        pass
