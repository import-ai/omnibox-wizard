import json as jsonlib
from typing import AsyncIterable

from openai.types.chat import ChatCompletionAssistantMessageParam

from src.wizard.grimoire.entity.api import ChatBaseResponse, ChatEOSResponse, ChatBOSResponse, ChatDeltaResponse, MessageDto
from src.wizard.grimoire.entity.retrieval import BaseRetrieval
from src.wizard.grimoire.entity.tools import ToolExecutorConfig


def retrieval_wrapper(
        tool_call_id: str,
        current_cite_cnt: int,
        retrieval_list: list[BaseRetrieval]
) -> MessageDto:
    citations = [retrieval.to_citation() for retrieval in retrieval_list]
    retrieval_prompt_list: list[str] = []
    for i, retrieval in enumerate(retrieval_list):
        prompt_list: list[str] = [
            f'<cite id="{current_cite_cnt + i + 1}" source="{retrieval.source()}">',
            retrieval.to_prompt(),
            '</cite>'
        ]
        retrieval_prompt_list.append("\n".join(prompt_list))
    retrieval_prompt: str = "\n\n".join(retrieval_prompt_list) or "Not found"
    content = "\n".join(["<retrievals>", retrieval_prompt, "</retrievals>"])
    return MessageDto.model_validate({
        "message": {"role": "tool", "tool_call_id": tool_call_id, "content": content},
        "attrs": {"citations": citations}
    })


def get_citation_cnt(messages: list[MessageDto]) -> int:
    return sum(len(message.attrs.citations) if message.attrs and message.attrs.citations else 0 for message in messages)


class ToolExecutor:
    def __init__(self, config: dict[str, ToolExecutorConfig]):
        self.config: dict[str, ToolExecutorConfig] = config
        self.tools: list[dict] = [config['schema'] for config in config.values()]

    async def astream(
            self,
            message_dtos: list[MessageDto],
    ) -> AsyncIterable[ChatBaseResponse]:
        message: ChatCompletionAssistantMessageParam = message_dtos[-1].message
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

                if function_name.endswith("search"):
                    message_dto: MessageDto = retrieval_wrapper(
                        tool_call_id=tool_call_id,
                        current_cite_cnt=get_citation_cnt(message_dtos),
                        retrieval_list=result
                    )
                else:
                    raise ValueError(f"Unknown function: {function_name}")

                yield ChatDeltaResponse.model_validate(message_dto.model_dump(exclude_none=True))
                yield message_dto
                yield ChatEOSResponse()
