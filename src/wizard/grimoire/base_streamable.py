from abc import abstractmethod
from typing import TypeVar, AsyncIterable

from src.common.trace_info import TraceInfo
from src.wizard.grimoire.entity.api import BaseChatRequest, ChatBaseResponse

ChatResponse = TypeVar("ChatResponse", bound=ChatBaseResponse)


class BaseStreamable:
    @abstractmethod
    async def astream(self, trace_info: TraceInfo, request: BaseChatRequest) -> AsyncIterable[ChatResponse]:
        raise NotImplementedError
