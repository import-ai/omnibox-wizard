import asyncio
import traceback
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from typing import AsyncGenerator, Callable

from httpx import AsyncClient, AsyncHTTPTransport
from opentelemetry import propagate, trace
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.trace import Status, StatusCode

from common.exception import CommonException
from common.logger import get_logger
from common.trace_info import TraceInfo
from omnibox_wizard.worker.callback_util import CallbackUtil
from omnibox_wizard.worker.config import WorkerConfig
from wizard_common.worker.entity import Task
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.worker.functions.collect_url import CollectUrlFunction
from omnibox_wizard.worker.functions.file_reader import FileReader
from omnibox_wizard.worker.functions.html_reader.html_reader import HTMLReaderV2
from omnibox_wizard.worker.functions.index import (
    DeleteConversation,
    DeleteIndex,
    UpsertIndex,
    UpsertMessageIndex,
)
from omnibox_wizard.worker.functions.tag_extractor import TagExtractor
from omnibox_wizard.worker.functions.title_generator import TitleGenerator
from omnibox_wizard.worker.functions.web_analysis import WebAnalysisFunction
from omnibox_wizard.worker.health_tracker import HealthTracker
from omnibox_wizard.worker.task_manager import TaskManager

tracer = trace.get_tracer(__name__)

# How often to report a heartbeat to the backend while a task is running.
HEARTBEAT_INTERVAL_SECONDS = 5

FILE_READER_FUNCTIONS: frozenset[str] = frozenset(
    {
        "file_reader_text",
        "file_reader_ppt",
        "file_reader_word",
    }
)
INDEX_FUNCTIONS: frozenset[str] = frozenset(
    {
        "upsert_index",
        "delete_index",
        "upsert_message_index",
        "delete_conversation",
    }
)
OTHER_FUNCTIONS: frozenset[str] = frozenset(
    {
        "collect",
        "collect_url",
        "web_analysis",
        "extract_tags",
        "generate_title",
    }
)
BASE_FUNCTIONS: frozenset[str] = (
    FILE_READER_FUNCTIONS | INDEX_FUNCTIONS | OTHER_FUNCTIONS
)


def compute_supported_functions(task_config) -> list[str]:
    enabled = set(BASE_FUNCTIONS)
    if task_config.functions:
        for func in [f.strip() for f in task_config.functions.split(",")]:
            op, func_name = func[0], func[1:]
            assert op in ("+", "-"), f"Invalid function config: {func}"
            if func_name == "all":
                if op == "+":
                    enabled = set(BASE_FUNCTIONS)
                else:
                    enabled = set()
            if op == "+":
                enabled.add(func_name)
            else:
                enabled.discard(func_name)
    return sorted(enabled)


class Worker:
    def __init__(
        self,
        config: WorkerConfig,
        worker_id: int,
        functions: list[str],
        health_tracker: HealthTracker | None = None,
    ):
        self.config: WorkerConfig = config
        self.worker_id = worker_id
        self.callback_util = CallbackUtil(config)
        self.health_tracker = health_tracker
        self.task_manager = TaskManager(config)

        self.file_reader: FileReader = FileReader(config)

        self.worker_dict: dict[str, BaseFunction] = {
            "collect": HTMLReaderV2(config),
            "collect_url": CollectUrlFunction(config),
            "web_analysis": WebAnalysisFunction(config),
            "upsert_index": UpsertIndex(config),
            "delete_index": DeleteIndex(config),
            # All base file_reader_* kinds share one handler; it dispatches on
            # the file extension internally.
            "file_reader_text": self.file_reader,
            "file_reader_ppt": self.file_reader,
            "file_reader_word": self.file_reader,
            "upsert_message_index": UpsertMessageIndex(config),
            "delete_conversation": DeleteConversation(config),
            "extract_tags": TagExtractor(config),
            "generate_title": TitleGenerator(config),
        }

        # Poll for the whole group, including disabled functions, so we can fail
        # them fast instead of leaving them to pend forever.
        self.polled_functions = functions
        self.supported_functions = set(compute_supported_functions(config.task))

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

    async def poll_task(self) -> Task | None:
        async with self._backend_client() as client:
            response = await client.post(
                "/internal/api/v1/wizard/tasks/poll",
                json={"functions": self.polled_functions},
            )
            response.raise_for_status()
            data = response.json().get("task")
            return Task.model_validate(data) if data else None

    async def _report_heartbeat(self, task_id: str) -> None:
        """Periodically tell the backend the task is still being worked on, so
        it is not treated as stale and re-claimed by another worker."""
        async with self._backend_client() as client:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                try:
                    response = await client.post(
                        f"/internal/api/v1/wizard/tasks/{task_id}/heartbeat"
                    )
                    response.raise_for_status()
                except Exception as e:
                    self.logger.warning(
                        f"Failed to report heartbeat for task {task_id}: {e}"
                    )

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

    async def process_polled_task(self, task: Task):
        if self.health_tracker:
            self.health_tracker.update_worker_status(self.worker_id, "running")

        trace_info: TraceInfo = self.get_trace_info(task)
        trace_info.info(
            {"message": "fetch_task"}
            | task.model_dump(include={"created_at", "started_at"})
        )
        trace_headers = task.payload.get("trace_headers", {}) if task.payload else {}
        parent_context = propagate.extract(trace_headers)
        resource_id: str | None = (
            task.payload.get("resource_id", None) if task.payload else None
        )

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
            heartbeat_task = asyncio.create_task(self._report_heartbeat(task.id))
            try:
                if task.function in self.supported_functions:
                    processed_task: Task = await self.process_task(task, trace_info)
                else:
                    processed_task = self.mark_unsupported(task, trace_info)
                await self.callback_util.send_callback(processed_task)
            finally:
                heartbeat_task.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat_task

        if self.health_tracker:
            self.health_tracker.update_worker_status(
                self.worker_id, "idle", datetime.now()
            )

    def mark_unsupported(self, task: Task, trace_info: TraceInfo) -> Task:
        """Fail a task whose function this wizard is not configured to run."""
        error_msg = f"Function '{task.function}' is not supported"
        task.exception = {"error": error_msg, "type": "UnsupportedFunctionError"}
        task.status = "error"
        task.updated_at = task.ended_at = datetime.now()

        span = trace.get_current_span()
        span.set_status(Status(StatusCode.ERROR, error_msg))
        span.set_attribute("error.message", error_msg)
        span.set_attribute("error.type", "UnsupportedFunctionError")

        trace_info.bind(error=error_msg).warning(
            task.model_dump(include={"created_at", "started_at", "ended_at"})
        )
        return task

    async def process_task(self, task: Task, trace_info: TraceInfo) -> Task:
        logging_func: Callable[[dict], None] = trace_info.info
        span = trace.get_current_span()

        try:
            # Use TaskManager to run with timeout and cancellation support
            output = await self.task_manager.run_with_timeout_and_cancellation(
                task, self.worker_router, trace_info
            )
            task.output = output
            task.status = "finished"
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
            task.status = "timeout"
            logging_func = trace_info.bind(error=error_msg).warning
            span.set_status(Status(StatusCode.ERROR, error_msg))
            span.set_attribute("error.message", error_msg)
            span.set_attribute("error.type", "TimeoutError")

        except asyncio.CancelledError:
            # Handle cancellation
            error_msg = "Task cancelled by user"
            task.exception = {"error": error_msg, "type": "CancelledError"}
            task.status = "canceled"
            logging_func = trace_info.bind(error=error_msg).info
            span.set_status(Status(StatusCode.ERROR, error_msg))
            span.set_attribute("error.message", error_msg)
            span.set_attribute("error.type", "CancelledError")

        except Exception as e:
            # Handle other exceptions
            task.exception = {
                "error": (
                    e.error
                    if isinstance(e, CommonException)
                    else CommonException.parse_exception(e)
                ),
                "traceback": traceback.format_exc(),
            }
            if isinstance(e, CommonException):
                task.exception["code"] = e.code
            task.status = "error"
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
