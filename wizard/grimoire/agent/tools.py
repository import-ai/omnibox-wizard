import json as jsonlib
from typing import AsyncIterable

from openai.types.chat import ChatCompletionAssistantMessageParam, ChatCompletionMessageParam

from wizard.config import OpenAIConfig
from wizard.grimoire.entity.api import (
    ChatBaseResponse, ChatEOSResponse, ChatBOSResponse, ChatDeltaResponse
)
from wizard.grimoire.entity.retrieval import BaseRetrieval
from wizard.grimoire.entity.tools import ToolExecutorConfig, BaseTool, FunctionMeta, ToolName
from wizard.grimoire.retriever.reranker import Reranker


def retrieval_wrapper(
        tool_call_id: str,
        current_cite_cnt: int,
        retrieval_list: list[BaseRetrieval]
) -> ChatDeltaResponse:
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
    return ChatDeltaResponse.model_validate({
        "message": {"role": "tool", "tool_call_id": tool_call_id, "content": content},
        "attrs": {"citations": citations}
    })


class ToolExecutor:
    def __init__(self, config: dict[str, ToolExecutorConfig]):
        self.config: dict[str, ToolExecutorConfig] = config
        self.tools: list[dict] = [config['schema'] for config in config.values()]

    @classmethod
    def build_search_tool(
            cls,
            tools: list[BaseTool],
            func_metas: list[FunctionMeta],
            reranker_config: OpenAIConfig | None = None
    ) -> ToolExecutorConfig:
        """
        Build a search tool that:

            1. Call all the search functions in parallel.
            2. Return the results in a single response.

        :param tools: List of Tool objects.
        :param func_metas: List of functions that return search results.
        :param reranker_config: Configuration for the reranker, if any (used to rank the search results).
        :return: ToolExecutorConfig for the search tool.
        """
        reranker: Reranker = Reranker(
            funcs=[t.to_func(m['func']) for t, m in zip(tools, func_metas)],
            config=reranker_config
        )
        name: str = "search"
        description: str = '\n'.join([
            "This tool can search for various types of information, they include but are not limited to:"
            "\n".join([m['description'] for m in func_metas]),
        ])

        return ToolExecutorConfig(
            schema={
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "The query to search for."
                            }
                        },
                        "required": [
                            "query"
                        ]
                    }
                }
            },
            func=reranker.search
        )

    @classmethod
    def from_tools(
            cls,
            tools: list[BaseTool],
            func_mapping: dict[ToolName, FunctionMeta],
            reranker_config: OpenAIConfig | None = None
    ) -> 'ToolExecutor':
        """
        Create a ToolExecutor from a list of Tool objects and a mapping of function names to FunctionMeta.

        :param tools: List of Tool objects.
        :param func_mapping: Mapping of function names to FunctionMeta.
        :param reranker_config: Configuration for OpenAI, if any (used to configure the reranker).
        :return: ToolExecutor instance.
        """
        func_metas: list[FunctionMeta] = [func_mapping[tool.name] for tool in tools]
        tool_executor_config: ToolExecutorConfig = cls.build_search_tool(
            tools=tools,
            func_metas=func_metas,
            reranker_config=reranker_config
        )
        return cls(config={
            tool['schema']['function']['name']: tool
            for tool in [tool_executor_config]
        })

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

                if function_name == "search":
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
