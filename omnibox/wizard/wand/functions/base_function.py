from omnibox.common.trace_info import TraceInfo
from omnibox.wizard.entity import Task


class BaseFunction:

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        raise NotImplementedError
