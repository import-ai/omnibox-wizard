from pydantic import BaseModel


class ToolExecuteResult(BaseModel):
    pass


class ToolExecutor:
    def __init__(self, tools: list[dict]):
        pass
