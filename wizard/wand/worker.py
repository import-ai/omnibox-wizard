import asyncio
from datetime import datetime
from typing import Optional, Callable

import httpx

from common.exception import CommonException
from common.logger import get_logger
from common.trace_info import TraceInfo
from wizard.config import Config
from wizard.entity import Task
from wizard.wand.functions.base_function import BaseFunction
from wizard.wand.functions.html_reader import HTMLReader
from wizard.wand.functions.index import CreateOrUpdateIndex, DeleteIndex


class Worker:
    def __init__(self, config: Config, worker_id: int):
        self.config: Config = config

        self.worker_id = worker_id

        self.worker_dict: dict[str, BaseFunction] = {
            "collect": HTMLReader(config.task.reader),
            "create_or_update_index": CreateOrUpdateIndex(config),
            "delete_index": DeleteIndex(config)
        }

        self.logger = get_logger(f"worker_{self.worker_id}")

    def get_trace_info(self, task: Task) -> TraceInfo:
        return TraceInfo(task.task_id, self.logger, payload={
            "task_id": task.task_id,
            "namespace_id": task.namespace_id,
            "function": task.function
        })

    async def run_once(self):
        task: Task = await self.fetch_task()
        if task:
            trace_info: TraceInfo = self.get_trace_info(task)
            trace_info.info({"message": "fetch_task"} | task.model_dump(include={"created_at", "started_at"}))
            processed_task: Task = await self.process_task(task, trace_info)
            await self.callback(processed_task, trace_info)
        else:
            self.logger.debug({"message": "No available task, waiting..."})

    async def run(self):
        while True:
            try:
                await self.run_once()
            except Exception as e:
                self.logger.exception({
                    "error": CommonException.parse_exception(e)
                })
            await asyncio.sleep(1)

    async def fetch_task(self) -> Optional[Task]:
        task: Optional[Task] = None
        try:
            async with httpx.AsyncClient(base_url=self.config.backend.base_url) as client:
                http_response: httpx.Response = await client.get(f"/internal/api/v1/tasks/fetch")
                logging_func: Callable = self.logger.debug if http_response.is_success else self.logger.error
                if http_response.status_code == 204:
                    logging_func({"status_code": http_response.status_code})
                    return task
                json_response = http_response.json()
                logging_func({"status_code": http_response.status_code, "response": json_response})
                if json_response:
                    return Task.model_validate(json_response | {
                        "user_id": json_response["user"]["id"],
                        "namespace_id": json_response["namespace"]["id"]
                    })
        except Exception as e:
            self.logger.exception({"error": CommonException.parse_exception(e)})
        return task

    async def process_task(self, task: Task, trace_info: TraceInfo) -> Task:
        logging_func: Callable[[dict], None] = trace_info.info

        try:
            output = await self.worker_router(task, trace_info)
        except Exception as e:
            # Update the task with the exception details
            task.exception = {"error": CommonException.parse_exception(e)}
            logging_func = trace_info.bind(error=CommonException.parse_exception(e)).exception
        else:
            # Update the task with the result
            task.output = output

        task.updated_at = task.ended_at = datetime.now()
        logging_func(task.model_dump(include={"created_at", "started_at", "ended_at"}))

        return task

    async def callback(self, task: Task, trace_info: TraceInfo):
        async with httpx.AsyncClient(base_url=self.config.backend.base_url) as client:
            http_response: httpx.Response = await client.post(
                f"/internal/api/v1/tasks/callback",
                json=task.model_dump(
                    exclude_none=True, mode="json", by_alias=True,
                    include={"task_id", "exception", "output", "ended_at"},
                ),
                headers={"X-Trace-ID": task.task_id}
            )
            logging_func: Callable[[dict], None] = trace_info.debug if http_response.is_success else trace_info.error
            logging_func({"status_code": http_response.status_code, "response": http_response.json()})

    async def worker_router(self, task: Task, trace_info: TraceInfo) -> dict:
        worker = self.worker_dict[task.function]
        return await worker.run(task, trace_info)
