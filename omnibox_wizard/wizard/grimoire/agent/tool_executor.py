import json as jsonlib
from typing import AsyncIterable

from openai.types.chat import ChatCompletionAssistantMessageParam
from opentelemetry import trace

from common.model_dump import model_dump
from common.trace_info import TraceInfo
from omnibox_wizard.wizard.grimoire.entity.api import (
    ChatBaseResponse,
    ChatEOSResponse,
    ChatBOSResponse,
    ChatDeltaResponse,
    MessageDto,
)
from omnibox_wizard.wizard.grimoire.entity.chunk import ResourceChunkRetrieval
from omnibox_wizard.wizard.grimoire.entity.resource import ResourceToolResult
from omnibox_wizard.wizard.grimoire.entity.retrieval import (
    BaseRetrieval,
    retrievals2prompt,
)
from omnibox_wizard.wizard.grimoire.entity.tools import (
    RESOURCE_TOOLS,
    SEARCH_TOOLS,
    ToolExecutorConfig,
)
from omnibox_wizard.wizard.grimoire.retriever.searxng import SearXNGRetrieval

tracer = trace.get_tracer(__name__)


def cmp(retrieval: BaseRetrieval) -> tuple[int, str, int, float]:
    if isinstance(
        retrieval, ResourceChunkRetrieval
    ):  # GROUP BY resource_id ORDER BY start_index ASC
        return 0, retrieval.chunk.resource_id, retrieval.chunk.start_index, 0.0
    elif isinstance(retrieval, SearXNGRetrieval):  # ORDER BY score.rerank DESC
        return 1, "", 0, -retrieval.score.rerank
    raise ValueError(f"Unknown retrieval type: {type(retrieval)}")


def retrieval_wrapper(tool_call_id: str, retrievals: list[BaseRetrieval]) -> MessageDto:
    retrievals = sorted(retrievals, key=cmp)
    content: str = retrievals2prompt(retrievals)
    return MessageDto.model_validate(
        {
            "message": {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            },
            "attrs": {
                "citations": [retrieval.to_citation() for retrieval in retrievals]
            },
        }
    )


def resource_tool_wrapper(
    tool_call_id: str, result: ResourceToolResult, current_cite_cnt: int = 0
) -> MessageDto:
    """Wrap resource tool result as MessageDto with citations."""
    content: str = result.to_tool_content()
    citations = result.to_citations()
    # Assign citation IDs
    for i, citation in enumerate(citations):
        citation.id = current_cite_cnt + i + 1
    return MessageDto.model_validate(
        {
            "message": {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            },
            "attrs": {"citations": citations} if citations else None,
        }
    )


def get_citation_cnt(messages: list[MessageDto]) -> int:
    return sum(
        len(message.attrs.citations) if message.attrs and message.attrs.citations else 0
        for message in messages
    )


class ToolExecutor:
    def __init__(self, config: dict[str, ToolExecutorConfig]):
        self.config: dict[str, ToolExecutorConfig] = config
        self.tools: list[dict] = [config["schema"] for config in config.values()]

    async def astream(
        self,
        message_dtos: list[MessageDto],
        trace_info: TraceInfo,
    ) -> AsyncIterable[ChatBaseResponse | MessageDto]:
        with tracer.start_as_current_span("tool_executor.astream"):
            message: ChatCompletionAssistantMessageParam = message_dtos[-1].message
            if tool_calls := message.get("tool_calls", []):
                for tool_call in tool_calls:
                    function = tool_call["function"]
                    tool_call_id: str = str(tool_call["id"])
                    function_args = jsonlib.loads(function["arguments"])
                    function_name = function["name"]
                    logger = trace_info.get_child(
                        addition_payload={
                            "tool_call_id": tool_call_id,
                            "function_name": function_name,
                            "function_args": function_args,
                        }
                    )

                    yield ChatBOSResponse(role="tool")
                    if function_name in self.config:
                        with tracer.start_as_current_span(
                            f"tool_executor.astream.{function_name}"
                        ) as func_span:
                            func_span.set_attributes(
                                {
                                    "tool_call_id": tool_call_id,
                                    "function_name": function_name,
                                    "function_args": jsonlib.dumps(
                                        function_args,
                                        ensure_ascii=False,
                                        separators=(",", ":"),
                                    ),
                                }
                            )
                            func = self.config[function_name]["func"]
                            result = await func(**function_args)
                            logger.info({"result": model_dump(result)})
                    else:
                        logger.error({"message": "Unknown function"})
                        raise ValueError(f"Unknown function: {function_name}")

                    if (
                        function_name in SEARCH_TOOLS
                        or function_name.endswith("search")
                    ):
                        # Search tool: result is list[BaseRetrieval], needs citation processing
                        current_cite_cnt: int = get_citation_cnt(message_dtos)
                        assert isinstance(result, list), (
                            f"Expected list of retrievals, got {type(result)}"
                        )
                        assert all(isinstance(r, BaseRetrieval) for r in result), (
                            f"Expected all items to be BaseRetrieval, got {[type(r) for r in result]}"
                        )
                        for i, r in enumerate(result):
                            r.id = current_cite_cnt + i + 1
                        message_dto: MessageDto = retrieval_wrapper(
                            tool_call_id=tool_call_id, retrievals=result
                        )
                    elif function_name in RESOURCE_TOOLS:
                        # Resource tool: result is ResourceToolResult, format as JSON with citations
                        assert isinstance(result, ResourceToolResult), (
                            f"Expected ResourceToolResult, got {type(result)}"
                        )
                        current_cite_cnt: int = get_citation_cnt(message_dtos)
                        message_dto: MessageDto = resource_tool_wrapper(
                            tool_call_id=tool_call_id,
                            result=result,
                            current_cite_cnt=current_cite_cnt,
                        )
                    else:
                        raise ValueError(f"Unknown function type: {function_name}")

                    yield ChatDeltaResponse.model_validate(
                        message_dto.model_dump(exclude_none=True)
                    )
                    yield message_dto
                    yield ChatEOSResponse()
