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


class Config(BaseModel):
    vector: VectorConfig


ENV_PREFIX: str = "MBW"
