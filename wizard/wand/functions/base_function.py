from wizard.entity import Task


class BaseFunction:
    async def run(self, task: Task) -> dict:
        raise NotImplementedError