import asyncio
import traceback
from datetime import datetime
from typing import Optional, Callable

import httpx
from opentelemetry import trace, propagate
from opentelemetry.trace import Status, StatusCode

from omnibox_wizard.common.exception import CommonException
from omnibox_wizard.common.logger import get_logger
from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.worker.callback_util import CallbackUtil
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.worker.functions.file_reader import FileReader
from omnibox_wizard.worker.functions.html_reader import HTMLReaderV2
from omnibox_wizard.worker.functions.index import DeleteConversation, UpsertIndex, DeleteIndex, UpsertMessageIndex
from omnibox_wizard.worker.functions.tag_extractor import TagExtractor
from omnibox_wizard.worker.functions.title_generator import TitleGenerator
from omnibox_wizard.worker.functions.video_note_generator import VideoNoteGenerator
from omnibox_wizard.worker.health_tracker import HealthTracker

tracer = trace.get_tracer(__name__)


class Worker:
    def __init__(self, config: WorkerConfig, worker_id: int, health_tracker: HealthTracker = None):
        self.config: WorkerConfig = config
        self.worker_id = worker_id
        self.callback_util = CallbackUtil(config)
        self.health_tracker = health_tracker

        self.worker_dict: dict[str, BaseFunction] = {
            "collect": HTMLReaderV2(config),
            "upsert_index": UpsertIndex(config),
            "delete_index": DeleteIndex(config),
            "file_reader": FileReader(config),
            "upsert_message_index": UpsertMessageIndex(config),
            "delete_conversation": DeleteConversation(config),
            "extract_tags": TagExtractor(config),
            "generate_title": TitleGenerator(config),
            "generate_video_note": VideoNoteGenerator(config),
        }

        self.logger = get_logger(f"worker_{self.worker_id}")

        if self.health_tracker:
            self.health_tracker.register_worker(self.worker_id)

    def get_trace_info(self, task: Task) -> TraceInfo:
        return TraceInfo(task.id, self.logger, payload={
            "task_id": task.id,
            "namespace_id": task.namespace_id,
            "function": task.function
        })

    async def run_once(self):
        task: Task | None = await self.fetch_task()
        if task:
            if self.health_tracker:
                self.health_tracker.update_worker_status(self.worker_id, "running")

            trace_info: TraceInfo = self.get_trace_info(task)
            trace_info.info({"message": "fetch_task"} | task.model_dump(include={"created_at", "started_at"}))
            trace_headers = task.payload.get("trace_headers", {}) if task.payload else {}
            parent_context = propagate.extract(trace_headers)

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
            ):
                processed_task: Task = await self.process_task(task, trace_info)
                await self.callback_util.send_callback(processed_task, trace_info)

            if self.health_tracker:
                self.health_tracker.update_worker_status(self.worker_id, "idle", datetime.now())
        else:
            if self.health_tracker:
                self.health_tracker.update_worker_status(self.worker_id, "idle")

    async def run(self):
        while True:
            try:
                await self.run_once()
            except httpx.ConnectError as e:
                self.logger.warning({
                    "message": "Failed to connect to backend",
                    "error": CommonException.parse_exception(e)
                })
            except Exception as e:
                if self.health_tracker:
                    self.health_tracker.increment_error_count(self.worker_id)
                    self.health_tracker.update_worker_status(self.worker_id, "error")
                self.logger.exception({
                    "error": CommonException.parse_exception(e)
                })
            await asyncio.sleep(1)

    async def fetch_task(self) -> Optional[Task]:
        task: Optional[Task] = None
        try:
            async with httpx.AsyncClient(base_url=self.config.backend.base_url) as client:
                http_response: httpx.Response = await client.get(f"/internal/api/v1/wizard/task")
                logging_func: Callable = self.logger.debug if http_response.is_success else self.logger.error
                if http_response.status_code == 204:
                    return None
                json_response = http_response.json()
                logging_func({"status_code": http_response.status_code, "response": json_response})
                return Task.model_validate(json_response)
        except Exception as e:
            self.logger.exception({"error": CommonException.parse_exception(e)})
        return task

    async def process_task(self, task: Task, trace_info: TraceInfo) -> Task:
        logging_func: Callable[[dict], None] = trace_info.info
        span = trace.get_current_span()

        try:
            output = await self.worker_router(task, trace_info)
            span.set_status(Status(StatusCode.OK))
        except Exception as e:
            task.exception = {"error": CommonException.parse_exception(e), "traceback": traceback.format_exc()}
            logging_func = trace_info.bind(error=CommonException.parse_exception(e)).exception

            # Record exception in span
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.set_attribute("error.message", str(e))
            span.set_attribute("error.type", type(e).__name__)
        else:
            task.output = output
            span.set_attribute("task.output_size", len(str(output)) if output else 0)

        task.updated_at = task.ended_at = datetime.now()
        logging_func(task.model_dump(include={"created_at", "started_at", "ended_at"}))

        return task

    async def worker_router(self, task: Task, trace_info: TraceInfo) -> dict:
        worker = self.worker_dict[task.function]
        return await worker.run(task, trace_info)
