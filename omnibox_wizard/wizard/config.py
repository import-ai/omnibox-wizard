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


GrimoireOpenAIConfigKey = Literal["mini", "default", "large", "large_thinking"]


class GrimoireOpenAIConfig(BaseModel):
    mini: OpenAIConfig = Field(default_factory=OpenAIConfig)
    default: OpenAIConfig
    large: OpenAIConfig = Field(default_factory=OpenAIConfig)
    large_thinking: OpenAIConfig = Field(default=None)

    def __getitem__(self, key: GrimoireOpenAIConfigKey) -> OpenAIConfig:
        openai_config: OpenAIConfig = getattr(self, key, None)
        if openai_config is None:
            raise KeyError(f"OpenAIConfig for key '{key}' not found.")
        return OpenAIConfig(
            base_url=openai_config.base_url or self.default.base_url,
            api_key=openai_config.api_key or self.default.api_key,
            model=openai_config.model or self.default.model
        )

    def get(self, key: GrimoireOpenAIConfigKey, default: OpenAIConfig | None = None) -> OpenAIConfig | None:
        try:
            return self[key]
        except KeyError:
            return default


class GrimoireConfig(BaseModel):
    openai: GrimoireOpenAIConfig = Field(default=None)
    custom_tool_call: bool = Field(default=True)


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
    tools: ToolsConfig


ENV_PREFIX: str = "OBW"
