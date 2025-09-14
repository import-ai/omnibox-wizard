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


class FunctionTimeoutConfig(BaseModel):
    collect: int = Field(default=None, description="Timeout for collect function")
    upsert_index: int = Field(default=60, description="Timeout for upsert_index function")
    delete_index: int = Field(default=60, description="Timeout for delete_index function")
    file_reader: int = Field(default=None, description="Timeout for file_reader function")
    upsert_message_index: int = Field(default=60, description="Timeout for upsert_message_index function")
    delete_conversation: int = Field(default=60, description="Timeout for delete_conversation function")
    extract_tags: int = Field(default=60, description="Timeout for extract_tags function")
    generate_title: int = Field(default=60, description="Timeout for generate_title function")
    generate_video_note: int = Field(default=None, description="Timeout for generate_video_note function")

    def get_timeout(self, function_name: str) -> int | None:
        """Get timeout for a specific function, returns None if not configured."""
        return getattr(self, function_name, None)


class TaskConfig(BaseModel):
    spliter: SpliterConfig = Field(default_factory=SpliterConfig)
    office_operator_base_url: str = Field(default=None)
    asr: OpenAIConfig = Field(default=None)
    pdf_reader_base_url: str = Field(default=None)
    docling_base_url: str = Field(default=None)
    timeout: int = Field(default=300, description="Default task timeout in seconds")
    function_timeouts: FunctionTimeoutConfig = Field(default_factory=FunctionTimeoutConfig, description="Function-specific timeout overrides")
    cancellation_check_interval: int = Field(
        default=3, description="Interval in seconds to check for task cancellation")


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
