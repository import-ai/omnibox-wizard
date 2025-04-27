from common.trace_info import TraceInfo
from wizard.entity import Task


class BaseFunction:
    async def async_init(self):
        pass

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        raise NotImplementedError
