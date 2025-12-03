from pydantic import BaseModel, Field

from omnibox_wizard.wizard.config import GrimoireConfig, VectorConfig


class BackendConfig(BaseModel):
    base_url: str


class SpliterConfig(BaseModel):
    chunk_size: int = Field(default=1024)
    chunk_overlap: int = Field(default=128)


class CallbackConfig(BaseModel):
    payload_size_threshold: int = Field(
        default=5, description="Size threshold in MB for uploading payload to S3"
    )


class FunctionTimeoutConfig(BaseModel):
    collect: int = Field(default=None, description="Timeout for collect function")
    upsert_index: int = Field(
        default=60, description="Timeout for upsert_index function"
    )
    delete_index: int = Field(
        default=60, description="Timeout for delete_index function"
    )
    file_reader: int = Field(
        default=600, description="Timeout for file_reader function"
    )
    upsert_message_index: int = Field(
        default=60, description="Timeout for upsert_message_index function"
    )
    delete_conversation: int = Field(
        default=60, description="Timeout for delete_conversation function"
    )
    extract_tags: int = Field(
        default=60, description="Timeout for extract_tags function"
    )
    generate_title: int = Field(
        default=60, description="Timeout for generate_title function"
    )
    generate_video_note: int = Field(
        default=600, description="Timeout for generate_video_note function"
    )

    def get_timeout(self, function_name: str) -> int | None:
        """Get timeout for a specific function, returns None if not configured."""
        return getattr(self, function_name, None)


class FileUploaderConfig(BaseModel):
    bucket: str = Field(default=None, description="S3/OSS bucket name")
    access_key: str = Field(default=None, description="Access key ID")
    secret_key: str = Field(default=None, description="Secret access key")
    endpoint: str = Field(
        default=None,
        description="Endpoint URL (e.g., https://oss-cn-hangzhou.aliyuncs.com)",
    )
    prefix: str = Field(
        default="temp-uploads", description="Key prefix for uploaded files"
    )
    expire_hours: int = Field(default=24, description="Presigned URL expiration hours")


class TaskConfig(BaseModel):
    functions: str = Field(
        default=None,
        description="Comma-separated list of functions to enable, started with + or - to add or remove. If None, all functions are enabled.",
        examples=["-all,+collect,+file_reader", "-collect"],
    )
    spliter: SpliterConfig = Field(default_factory=SpliterConfig)
    office_operator_base_url: str = Field(default=None)
    docling_base_url: str = Field(default=None)
    timeout: int = Field(default=300, description="Default task timeout in seconds")
    function_timeouts: FunctionTimeoutConfig = Field(
        default_factory=FunctionTimeoutConfig,
        description="Function-specific timeout overrides",
    )
    cancellation_check_interval: int = Field(
        default=3, description="Interval in seconds to check for task cancellation"
    )


class HealthConfig(BaseModel):
    enabled: bool = Field(default=True, description="Enable health check server")
    port: int = Field(default=8000, description="Port for health check server")


class ConsumerConfig(BaseModel):
    topic: str = Field(default="omnibox-tasks")
    group: str = Field(default="omnibox-wizard")
    concurrency: int = Field(default=10)


class RateLimiterConfig(BaseModel):
    file_reader_doc: int = Field(default=2)
    file_reader_md: int = Field(default=2)
    file_reader_txt: int = Field(default=2)


class WorkerConfig(BaseModel):
    vector: VectorConfig
    task: TaskConfig = Field(default_factory=TaskConfig)
    backend: BackendConfig
    callback: CallbackConfig = Field(default_factory=CallbackConfig)
    grimoire: GrimoireConfig = Field(default=None)
    health: HealthConfig = Field(default_factory=HealthConfig)
    consumer: ConsumerConfig = Field(default_factory=ConsumerConfig)
    rate: RateLimiterConfig = Field(default_factory=RateLimiterConfig)


ENV_PREFIX: str = "OBW"
