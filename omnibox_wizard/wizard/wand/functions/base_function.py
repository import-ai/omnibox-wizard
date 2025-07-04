from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.wizard.entity import Task


class BaseFunction:

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        raise NotImplementedError
