from typing import Literal

from openai import NOT_GIVEN, NotGiven
from pydantic import BaseModel, Field

from wizard_common.config import OpenAIConfig


class BackendConfig(BaseModel):
    base_url: str


class VectorConfig(BaseModel):
    embedding: OpenAIConfig
    host: str
    port: int = Field(default=8000)
    meili_api_key: str = Field(default=None)
    batch_size: int = Field(default=1)
    max_results: int = Field(default=10)
    wait_timeout: int = Field(default=0)
    dimension: int = Field(default=1536)


GrimoireOpenAIConfigKey = Literal["mini", "default", "large"]


class GrimoireOpenAIConfig(BaseModel):
    mini: OpenAIConfig = Field(default_factory=OpenAIConfig)
    mini_thinking: OpenAIConfig = Field(default=None)
    default: OpenAIConfig
    default_thinking: OpenAIConfig = Field(default=None)
    large: OpenAIConfig = Field(default_factory=OpenAIConfig)
    large_thinking: OpenAIConfig = Field(default=None)

    def get_config(
        self,
        key: GrimoireOpenAIConfigKey,
        thinking: bool = False,
        default: OpenAIConfig | None | NotGiven = NOT_GIVEN,
    ) -> OpenAIConfig | None:
        k = key if not thinking else f"{key}_thinking"
        openai_config: OpenAIConfig = getattr(self, k, None)
        if openai_config is None:
            if isinstance(default, NotGiven):
                raise KeyError(f"OpenAIConfig for key '{k}' not found.")
            return default
        return OpenAIConfig(
            base_url=openai_config.base_url or self.default.base_url,
            api_key=openai_config.api_key or self.default.api_key,
            model=openai_config.model or self.default.model,
        )


class GrimoireConfig(BaseModel):
    openai: GrimoireOpenAIConfig = Field(default=None)
    custom_tool_call: bool = Field(default=False)


class RerankerConfig(BaseModel):
    openai: OpenAIConfig = Field(default=None)
    threshold: float = Field(default=None)
    k: int = Field(default=None)


class SearXNGConfig(BaseModel):
    base_url: str
    engines: str | None = Field(default=None)

class ToolsConfig(BaseModel):
    searxng: SearXNGConfig
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    resource_api: BackendConfig = Field(default_factory=BackendConfig)


class Config(BaseModel):
    vector: VectorConfig
    grimoire: GrimoireConfig
    tools: ToolsConfig


ENV_PREFIX: str = "OBW"
