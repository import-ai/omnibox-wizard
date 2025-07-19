from pydantic import BaseModel, Field

from omnibox_wizard.wizard.config import OpenAIConfig, VectorConfig


class BackendConfig(BaseModel):
    base_url: str


class SpliterConfig(BaseModel):
    chunk_size: int = Field(default=1024)
    chunk_overlap: int = Field(default=128)


class TaskConfig(BaseModel):
    spliter: SpliterConfig = Field(default_factory=SpliterConfig)
    office_operator_base_url: str = Field(default=None)
    asr: OpenAIConfig = Field(default=None)
    pdf_reader_base_url: str


class WorkerConfig(BaseModel):
    vector: VectorConfig
    task: TaskConfig
    backend: BackendConfig


ENV_PREFIX: str = "OBW"
