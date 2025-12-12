import asyncio
import traceback
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Callable

from httpx import AsyncClient, AsyncHTTPTransport, HTTPStatusError
from opentelemetry import propagate, trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.trace import Status, StatusCode

from common.exception import CommonException
from common.logger import get_logger
from common.trace_info import TraceInfo
from omnibox_wizard.worker.callback_util import CallbackUtil
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Message, Task
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.worker.functions.file_reader import FileReader
from omnibox_wizard.worker.functions.html_reader import HTMLReaderV2
from omnibox_wizard.worker.functions.index import (
    DeleteConversation,
    DeleteIndex,
    UpsertIndex,
    UpsertMessageIndex,
)
from omnibox_wizard.worker.functions.tag_extractor import TagExtractor
from omnibox_wizard.worker.functions.title_generator import TitleGenerator
from omnibox_wizard.worker.health_tracker import HealthTracker
from omnibox_wizard.worker.rate_limiter import RateLimiter
from omnibox_wizard.worker.task_manager import TaskManager

tracer = trace.get_tracer(__name__)


class Worker:
    def __init__(
        self,
        config: WorkerConfig,
        worker_id: int,
        health_tracker: HealthTracker,
        rate_limiter: RateLimiter,
    ):
        self.config: WorkerConfig = config
        self.worker_id = worker_id
        self.callback_util = CallbackUtil(config)
        self.health_tracker = health_tracker
        self.task_manager = TaskManager(config)
        self.rate_limiter = rate_limiter

        self.file_reader: FileReader = FileReader(config)

        self.worker_dict: dict[str, BaseFunction] = {
            "collect": HTMLReaderV2(config),
            "upsert_index": UpsertIndex(config),
            "delete_index": DeleteIndex(config),
            "file_reader": self.file_reader,
            "upsert_message_index": UpsertMessageIndex(config),
            "delete_conversation": DeleteConversation(config),
            "extract_tags": TagExtractor(config),
            "generate_title": TitleGenerator(config),
        }

        functions_enabled = set(self.worker_dict.keys())
        if config.task.functions:
            functions_config = [f.strip() for f in config.task.functions.split(",")]
            for func in functions_config:
                op, func_name = func[0], func[1:]
                assert op in ("+", "-"), f"Invalid function config: {func}"
                if func_name == "all":
                    if op == "+":
                        functions_enabled = set(self.worker_dict.keys())
                    else:
                        functions_enabled = set()
                if op == "+":
                    functions_enabled.add(func_name)
                else:
                    functions_enabled.discard(func_name)
        self.supported_functions = list(functions_enabled)

        self.logger = get_logger(f"worker_{self.worker_id}")

        if self.health_tracker:
            self.health_tracker.register_worker(self.worker_id)

    @asynccontextmanager
    async def _backend_client(self) -> AsyncGenerator[AsyncClient, None]:
        async with AsyncClient(
            base_url=self.config.backend.base_url,
            transport=AsyncHTTPTransport(retries=3),
            timeout=30,
        ) as client:
            HTTPXClientInstrumentor.instrument_client(client)
            yield client

    async def _start_task(self, task_id: str) -> Task | None:
        async with self._backend_client() as client:
            try:
                response = await client.post(
                    f"/internal/api/v1/wizard/tasks/{task_id}/start"
                )
                response.raise_for_status()
                return Task.model_validate(response.json())
            except HTTPStatusError as e:
                data = e.response.json()
                if data.get("code") in [
                    "task_ended",
                    "task_canceled",
                    "task_not_found",
                ]:
                    return None
                raise

    def get_trace_info(self, task: Task) -> TraceInfo:
        return TraceInfo(
            task.id,
            self.logger,
            payload={
                "task_id": task.id,
                "namespace_id": task.namespace_id,
                "function": task.function,
            },
        )

    async def process_message(self, msg: Message):
        if msg.function not in self.supported_functions:
            return
        if msg.function == "file_reader":
            file_name = msg.meta.get("file_name", "")
            file_ext = Path(file_name).suffix.lower()
            if file_ext not in self.file_reader.supported_extensions:
                return

        if self.health_tracker:
            self.health_tracker.update_worker_status(self.worker_id, "running")

        async with self.rate_limiter.limit(msg):
            task = await self._start_task(msg.task_id)
            if task is not None:
                trace_info: TraceInfo = self.get_trace_info(task)
                trace_info.info(
                    {"message": "fetch_task"}
                    | task.model_dump(include={"created_at", "started_at"})
                )
                trace_headers = (
                    task.payload.get("trace_headers", {}) if task.payload else {}
                )
                parent_context = propagate.extract(trace_headers)
                resource_id: str = task.payload.get("resource_id", None)

                with tracer.start_as_current_span(
                    f"worker.process_task.{task.function}",
                    context=parent_context,
                    attributes={
                        "task.id": task.id,
                        "task.function": task.function,
                        "task.namespace_id": task.namespace_id,
                        "task.user_id": task.user_id,
                        "task.priority": task.priority,
                        "worker.id": str(self.worker_id),
                    }
                    | ({"task.resource_id": resource_id} if resource_id else {}),
                ):
                    processed_task: Task = await self.process_task(task, trace_info)
                    await self.callback_util.send_callback(processed_task)

        if self.health_tracker:
            self.health_tracker.update_worker_status(
                self.worker_id, "idle", datetime.now()
            )

    async def process_task(self, task: Task, trace_info: TraceInfo) -> Task:
        logging_func: Callable[[dict], None] = trace_info.info
        span = trace.get_current_span()

        try:
            # Use TaskManager to run with timeout and cancellation support
            output = await self.task_manager.run_with_timeout_and_cancellation(
                task, self.worker_router, trace_info
            )
            task.output = output
            span.set_status(Status(StatusCode.OK))
            span.set_attribute("task.output_size", len(str(output)) if output else 0)

        except asyncio.TimeoutError:
            # Handle timeout - calculate actual timeout used
            function_timeout = self.config.task.function_timeouts.get_timeout(
                task.function
            )
            actual_timeout = (
                function_timeout
                if function_timeout is not None
                else self.config.task.timeout
            )
            timeout_source = (
                "function-specific" if function_timeout is not None else "global"
            )

            error_msg = f"Task execution timeout after {actual_timeout} seconds ({timeout_source} timeout)"
            task.exception = {
                "error": error_msg,
                "timeout": actual_timeout,
                "timeout_source": timeout_source,
                "type": "TimeoutError",
            }
            logging_func = trace_info.bind(error=error_msg).warning
            span.set_status(Status(StatusCode.ERROR, error_msg))
            span.set_attribute("error.message", error_msg)
            span.set_attribute("error.type", "TimeoutError")

        except asyncio.CancelledError:
            # Handle cancellation
            error_msg = "Task cancelled by user"
            task.exception = {"error": error_msg, "type": "CancelledError"}
            logging_func = trace_info.bind(error=error_msg).info
            span.set_status(Status(StatusCode.ERROR, error_msg))
            span.set_attribute("error.message", error_msg)
            span.set_attribute("error.type", "CancelledError")

        except Exception as e:
            # Handle other exceptions
            task.exception = {
                "error": CommonException.parse_exception(e),
                "traceback": traceback.format_exc(),
            }
            logging_func = trace_info.bind(
                error=CommonException.parse_exception(e)
            ).exception

            # Record exception in span
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.set_attribute("error.message", str(e))
            span.set_attribute("error.type", type(e).__name__)

        task.updated_at = task.ended_at = datetime.now()
        logging_func(task.model_dump(include={"created_at", "started_at", "ended_at"}))

        return task

    async def worker_router(self, task: Task, trace_info: TraceInfo) -> dict:
        worker = self.worker_dict[task.function]
        return await worker.run(task, trace_info)
