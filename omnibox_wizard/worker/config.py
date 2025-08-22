from pydantic import BaseModel, Field

from omnibox_wizard.wizard.config import OpenAIConfig, VectorConfig, GrimoireConfig


class BackendConfig(BaseModel):
    base_url: str


class SpliterConfig(BaseModel):
    chunk_size: int = Field(default=1024)
    chunk_overlap: int = Field(default=128)


class CallbackConfig(BaseModel):
    chunk_size: int = Field(default=5242880, description="Chunk size for large callback payloads (default: 5MB)")
    use_chunked: bool = Field(default=True, description="Enable chunked callback for large payloads")


class TaskConfig(BaseModel):
    spliter: SpliterConfig = Field(default_factory=SpliterConfig)
    office_operator_base_url: str = Field(default=None)
    asr: OpenAIConfig = Field(default=None)
    pdf_reader_base_url: str
    use_docling: bool = Field(default=False, description="Use Docling instead of MarkItDown for office document conversion")


class HealthConfig(BaseModel):
    enabled: bool = Field(default=True, description="Enable health check server")
    port: int = Field(default=8000, description="Port for health check server")


class WorkerConfig(BaseModel):
    vector: VectorConfig
    task: TaskConfig
    backend: BackendConfig
    callback: CallbackConfig = Field(default_factory=CallbackConfig)
    grimoire: GrimoireConfig = Field(default=None)
    health: HealthConfig = Field(default_factory=HealthConfig)


ENV_PREFIX: str = "OBW"
