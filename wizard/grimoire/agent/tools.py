import json as jsonlib
from typing import AsyncIterable

from openai.types.chat import ChatCompletionAssistantMessageParam, ChatCompletionMessageParam

from wizard.grimoire.entity.api import (
    ChatBaseResponse, ChatEOSResponse, ChatBOSResponse, ChatDeltaResponse
)
from wizard.grimoire.entity.retrieval import BaseRetrieval
from wizard.grimoire.entity.tools import ToolExecutorConfig


def retrieval_wrapper(
        tool_call_id: str,
        current_cite_cnt: int,
        retrieval_list: list[BaseRetrieval]
) -> ChatDeltaResponse:
    citations = [retrieval.to_citation() for retrieval in retrieval_list]
    retrieval_prompt_list: list[str] = []
    for i, retrieval in enumerate(retrieval_list):
        prompt_list: list[str] = [
            f'<cite id="{current_cite_cnt + i + 1}">',
            retrieval.to_prompt(),
            '</cite>'
        ]
        retrieval_prompt_list.append("\n".join(prompt_list))
    response = "\n\n".join(retrieval_prompt_list) or "Not found"
    return ChatDeltaResponse.model_validate({
        "message": {"role": "tool", "tool_call_id": tool_call_id, "content": response},
        "attrs": {"citations": citations}
    })


class ToolExecutor:
    def __init__(self, config: dict[str, ToolExecutorConfig]):
        self.config: dict[str, ToolExecutorConfig] = config
        self.tools: list[dict] = [config['schema'] for config in config.values()]

    async def astream(
            self,
            messages: list[ChatCompletionMessageParam],
            current_cite_cnt: int
    ) -> AsyncIterable[ChatBaseResponse]:
        message: ChatCompletionAssistantMessageParam = messages[-1]
        if tool_calls := message.get('tool_calls', []):
            for tool_call in tool_calls:
                function = tool_call['function']
                tool_call_id: str = str(tool_call['id'])
                function_args = jsonlib.loads(function['arguments'])
                function_name = function['name']

                yield ChatBOSResponse(role="tool")
                if function_name in self.config:
                    func = self.config[function_name]['func']
                    result = await func(**function_args)
                else:
                    raise ValueError(f"Unknown function: {function_name}")

                if function_name.endswith("_search"):
                    chat_delta_response: ChatDeltaResponse = retrieval_wrapper(
                        tool_call_id=tool_call_id,
                        current_cite_cnt=current_cite_cnt,
                        retrieval_list=result
                    )
                    if (attrs := chat_delta_response.attrs) and attrs.citations:
                        current_cite_cnt += len(attrs.citations)
                else:
                    raise ValueError(f"Unknown function: {function_name}")

                yield chat_delta_response
                yield ChatEOSResponse()
