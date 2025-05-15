from common.trace_info import TraceInfo
from wizard.entity import Task


class BaseFunction:

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        raise NotImplementedError
