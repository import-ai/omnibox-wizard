from common.trace_info import TraceInfo
from wizard_common.worker.entity import Task


class BaseFunction:
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        raise NotImplementedError
