from src.common.trace_info import TraceInfo
from src.wizard.entity import Task


class BaseFunction:

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        raise NotImplementedError
