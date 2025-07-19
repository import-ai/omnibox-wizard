import json as jsonlib
from typing import AsyncIterable

from openai.types.chat import ChatCompletionAssistantMessageParam

from omnibox_wizard.common.model_dump import model_dump
from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.wizard.grimoire.entity.api import (
    ChatBaseResponse, ChatEOSResponse, ChatBOSResponse, ChatDeltaResponse, MessageDto
)
from omnibox_wizard.wizard.grimoire.entity.chunk import ResourceChunkRetrieval
from omnibox_wizard.wizard.grimoire.entity.retrieval import BaseRetrieval, retrievals2prompt
from omnibox_wizard.wizard.grimoire.entity.tools import ToolExecutorConfig
from omnibox_wizard.wizard.grimoire.retriever.searxng import SearXNGRetrieval


def cmp(retrieval: BaseRetrieval) -> tuple[int, str, int, float]:
    if isinstance(retrieval, ResourceChunkRetrieval):  # GROUP BY resource_id ORDER BY start_index ASC
        return 0, retrieval.chunk.resource_id, retrieval.chunk.start_index, 0.
    elif isinstance(retrieval, SearXNGRetrieval):  # ORDER BY score.rerank DESC
        return 1, '', 0, -retrieval.score.rerank
    raise ValueError(f"Unknown retrieval type: {type(retrieval)}")


def retrieval_wrapper(
        tool_call_id: str,
        current_cite_cnt: int,
        retrievals: list[BaseRetrieval]
) -> MessageDto:
    retrievals = sorted(retrievals, key=cmp)
    content: str = retrievals2prompt(retrievals, current_cite_cnt)
    return MessageDto.model_validate({
        "message": {"role": "tool", "tool_call_id": tool_call_id, "content": content},
        "attrs": {"citations": [retrieval.to_citation() for retrieval in retrievals]}
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
            trace_info: TraceInfo,
    ) -> AsyncIterable[ChatBaseResponse]:
        message: ChatCompletionAssistantMessageParam = message_dtos[-1].message
        if tool_calls := message.get('tool_calls', []):
            for tool_call in tool_calls:
                function = tool_call['function']
                tool_call_id: str = str(tool_call['id'])
                function_args = jsonlib.loads(function['arguments'])
                function_name = function['name']
                logger = trace_info.get_child(addition_payload={
                    "tool_call_id": tool_call_id,
                    "function_name": function_name,
                    "function_args": function_args,
                })

                yield ChatBOSResponse(role="tool")
                if function_name in self.config:
                    func = self.config[function_name]['func']
                    result = await func(**function_args)
                    logger.info({"result": model_dump(result)})
                else:
                    logger.error({"message": "Unknown function"})
                    raise ValueError(f"Unknown function: {function_name}")

                if function_name.endswith("search"):
                    message_dto: MessageDto = retrieval_wrapper(
                        tool_call_id=tool_call_id,
                        current_cite_cnt=get_citation_cnt(message_dtos),
                        retrievals=result
                    )
                else:
                    raise ValueError(f"Unknown function: {function_name}")

                yield ChatDeltaResponse.model_validate(message_dto.model_dump(exclude_none=True))
                yield message_dto
                yield ChatEOSResponse()
