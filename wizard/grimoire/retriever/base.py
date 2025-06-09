from abc import ABC
from typing import Callable, Awaitable

from wizard.grimoire.entity.retrieval import BaseRetrieval
from wizard.grimoire.entity.tools import BaseTool, ToolExecutorConfig

SearchFunction = Callable[[str], Awaitable[list[BaseRetrieval]]]


class BaseRetriever(ABC):
    def get_tool_executor_config(self, tool: BaseTool, **kwargs) -> ToolExecutorConfig:
        return ToolExecutorConfig(
            name=tool.name,
            func=self.get_function(tool, **kwargs),
            schema=self.get_schema(),
        )

    def get_function(self, tool: BaseTool, **kwargs) -> SearchFunction:
        raise NotImplementedError

    def get_schema(self) -> dict:
        return self.generate_schema(name="search", description=f"Search for information.")

    @property
    def name(self) -> str:
        return self.get_schema()["function"]["name"]

    @classmethod
    def generate_schema(cls, name: str, description: str) -> dict:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The query to search for."
                        }
                    },
                    "required": [
                        "query"
                    ]
                }
            }
        }
