from typing import Literal

from openai import AsyncOpenAI, AsyncStream
from openai.types.chat import ChatCompletion, ChatCompletionChunk
from pydantic import BaseModel, Field


class OpenAIConfig(BaseModel):
    api_key: str = Field(default=None)
    model: str = Field(default=None)
    base_url: str = Field(default=None)

    async def chat(self, *, model: str = None, **kwargs) -> ChatCompletion | AsyncStream[ChatCompletionChunk]:
        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        return await client.chat.completions.create(**(kwargs | {"model": model or self.model}))


class VectorConfig(BaseModel):
    embedding: OpenAIConfig
    host: str
    port: int = Field(default=8000)
    meili_api_key: str = Field(default=None)
    batch_size: int = Field(default=1)
    max_results: int = Field(default=10)


class GrimoireOpenAIConfig(BaseModel):
    mini: OpenAIConfig = Field(default_factory=OpenAIConfig)
    default: OpenAIConfig
    large: OpenAIConfig = Field(default_factory=OpenAIConfig)

    def __getitem__(self, key: Literal["mini", "default", "large"]) -> OpenAIConfig:
        if key == "mini":
            return OpenAIConfig(
                base_url=self.mini.base_url or self.default.base_url,
                api_key=self.mini.api_key or self.default.api_key,
                model=self.mini.model or self.default.model
            )
        elif key == "large":
            return OpenAIConfig(
                base_url=self.large.base_url or self.default.base_url,
                api_key=self.large.api_key or self.default.api_key,
                model=self.large.model or self.default.model
            )
        else:
            return self.default


class GrimoireConfig(BaseModel):
    openai: GrimoireOpenAIConfig = Field(default=None)
    custom_tool_call: bool | None = Field(default=None)


class BackendConfig(BaseModel):
    base_url: str


class SpliterConfig(BaseModel):
    chunk_size: int = Field(default=1024)
    chunk_overlap: int = Field(default=128)


class TaskConfig(BaseModel):
    spliter: SpliterConfig = Field(default_factory=SpliterConfig)
    office_operator_base_url: str = Field(default=None)
    asr: OpenAIConfig = Field(default=None)


class RerankerConfig(BaseModel):
    openai: OpenAIConfig = Field(default=None)
    threshold: float = Field(default=None)
    k: int = Field(default=None)


class SearXNGConfig(BaseModel):
    base_url: str
    engines: str | None = Field(default=None)


class ToolsConfig(BaseModel):
    searxng: SearXNGConfig
    reranker: RerankerConfig = Field(default=None)


class Config(BaseModel):
    vector: VectorConfig
    grimoire: GrimoireConfig
    backend: BackendConfig
    tools: ToolsConfig


class WorkerConfig(BaseModel):
    vector: VectorConfig
    task: TaskConfig
    backend: BackendConfig


ENV_PREFIX: str = "OBW"
