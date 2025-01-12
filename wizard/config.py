from typing import Optional

from pydantic import BaseModel, Field


class OpenAIConfig(BaseModel):
    api_key: str
    model: str = Field(default="gpt-3.5-turbo")
    base_url: str = Field(default="https://api.openai.com/v1")


class VectorConfig(BaseModel):
    embedding: OpenAIConfig
    host: str
    port: int = Field(default=8000)
    batch_size: int = Field(default=1)
    max_results: int = Field(default=10)


class RewriteConfig(BaseModel):
    openai: Optional[OpenAIConfig] = Field(default=None)
    max_results: int = Field(default=10)


class GrimoireConfig(BaseModel):
    openai: OpenAIConfig
    rewrite: RewriteConfig = Field(default_factory=RewriteConfig)


class DBConfig(BaseModel):
    url: str = Field(default=None, examples=["postgresql+asyncpg://{username}:{password}@{host}:{port}/{db_name}"])


class BackendConfig(BaseModel):
    base_url: str


class Config(BaseModel):
    vector: VectorConfig
    grimoire: GrimoireConfig
    db: DBConfig = Field(default_factory=DBConfig)
    backend: BackendConfig


ENV_PREFIX: str = "MBW"
