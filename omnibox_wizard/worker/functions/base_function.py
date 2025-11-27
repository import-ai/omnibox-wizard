from common.trace_info import TraceInfo
from omnibox_wizard.worker.entity import Task


class BaseFunction:
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        raise NotImplementedError
