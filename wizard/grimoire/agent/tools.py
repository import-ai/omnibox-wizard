import json as jsonlib
from typing import AsyncIterable

from openai.types.chat import ChatCompletionAssistantMessageParam, ChatCompletionMessageParam
from pydantic import BaseModel

from wizard.grimoire.entity.api import (
    ChatOpenAIMessageResponse, ChatBaseResponse, ChatCitationListResponse, ToolCallResponse
)
from wizard.grimoire.entity.retrieval import BaseRetrieval
from wizard.grimoire.entity.tools import ToolExecutorConfig


class ToolExecuteResult(BaseModel):
    openai_message_response: ChatOpenAIMessageResponse
    response: ChatBaseResponse


def get_current_cite_cnt(messages: list[ChatCompletionMessageParam]) -> int:
    current_cite_cnt: int = 0
    for message in messages:
        if message['role'] == 'tool':
            content = message['content']
            for line in content.split("\n"):
                if line.startswith("<cite:") and line.endswith(">"):
                    cite_index: int = int(line.lstrip("<cite:").rstrip(">"))
                    current_cite_cnt += 1
                    assert cite_index == current_cite_cnt
    return current_cite_cnt


def retrieval_wrapper(
        tool_call_id: str,
        current_cite_cnt: int,
        retrieval_list: list[BaseRetrieval]
) -> ToolExecuteResult:
    citation_list_response: ChatCitationListResponse = ChatCitationListResponse(
        citation_list=[retrieval.to_citation() for retrieval in retrieval_list],
    )
    retrieval_prompt_list: list[str] = []
    for i, retrieval in enumerate(retrieval_list):
        prompt_list: list[str] = [
            f"<cite:{current_cite_cnt + i + 1}>",
            retrieval.to_prompt()
        ]
        retrieval_prompt_list.append("\n".join(prompt_list))
    prompt = "\n\n".join(retrieval_prompt_list)
    return ToolExecuteResult(
        openai_message_response=ChatOpenAIMessageResponse(
            message={"role": "tool", "tool_call_id": tool_call_id, "content": prompt}
        ),
        response=citation_list_response
    )


class ToolExecutor:
    def __init__(self, config: dict[str, ToolExecutorConfig]):
        self.config: dict[str, ToolExecutorConfig] = config
        self.tools: list[dict] = [config['schema'] for config in config.values()]

    async def astream(self, messages: list[ChatCompletionMessageParam]) -> AsyncIterable[ChatBaseResponse]:
        message: ChatCompletionAssistantMessageParam = messages[-1]
        if tool_calls := message.get('tool_calls', []):
            for tool_call in tool_calls:
                function = tool_call['function']
                tool_call_id: str = str(tool_call['id'])
                function_args = jsonlib.loads(function['arguments'])
                function_name = function['name']

                yield ToolCallResponse.model_validate({
                    "tool_call": {"id": tool_call_id, "function": {"name": function_name, "arguments": function_args}}
                })

                if function_name in self.config:
                    func = self.config[function_name]['func']
                    result = await func(**function_args)
                else:
                    raise ValueError(f"Unknown function: {function_name}")

                if function_name.endswith("_search"):
                    current_cite_cnt: int = get_current_cite_cnt(messages)
                    tool_execute_result: ToolExecuteResult = retrieval_wrapper(
                        tool_call_id=tool_call_id,
                        current_cite_cnt=current_cite_cnt,
                        retrieval_list=result
                    )
                else:
                    raise ValueError(f"Unknown function: {function_name}")

                yield tool_execute_result.openai_message_response
                yield tool_execute_result.response
