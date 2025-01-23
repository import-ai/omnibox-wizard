import asyncio
from datetime import datetime
from typing import Optional, Callable

import httpx
from sqlalchemy import select, func, desc, asc
from sqlalchemy.exc import IntegrityError

from common.exception import CommonException
from common.logger import get_logger
from common.trace_info import TraceInfo
from wizard.config import Config
from wizard.db import get_session_factory
from wizard.db.entity import Task as ORMTask
from wizard.entity import Task
from wizard.wand.functions.html_reader import HTMLReader
from wizard.wand.functions.index import CreateOrUpdateIndex, DeleteIndex


class Worker:
    def __init__(self, config: Config, worker_id: int):
        self.config: Config = config

        self.worker_id = worker_id

        self.html_reader = HTMLReader(config.task.reader)
        self.create_or_update_index: CreateOrUpdateIndex = CreateOrUpdateIndex(config)
        self.delete_index: DeleteIndex = DeleteIndex(config)

        self.logger = get_logger(f"worker_{self.worker_id}")
        self.session_factory = get_session_factory(config.db.url)

    def get_trace_info(self, task: Task) -> TraceInfo:
        return TraceInfo(task.task_id, self.logger, payload={
            "task_id": task.task_id,
            "namespace_id": task.namespace_id,
            "function": task.function
        })

    async def run_once(self):
        task: Task = await self.fetch_and_claim_task()
        if task:
            trace_info: TraceInfo = self.get_trace_info(task)
            trace_info.info({"message": "fetch_task"} | task.model_dump(include={"created_at", "started_at"}))
            processed_task: Task = await self.process_task(task, trace_info)
            await self.callback(processed_task, trace_info)
        else:
            self.logger.debug({
                "message": "No available task, waiting..."
            })

    async def run(self):
        while True:
            try:
                await self.run_once()
            except Exception as e:
                self.logger.exception({
                    "error": CommonException.parse_exception(e)
                })
            await asyncio.sleep(1)

    async def fetch_and_claim_task(self) -> Optional[Task]:
        task: Optional[Task] = None
        async with self.session_factory() as session:
            try:
                async with session.begin():
                    # Subquery to count running tasks per user
                    running_tasks_sub_query = (
                        select(
                            ORMTask.namespace_id,
                            func.count(ORMTask.task_id).label('running_count')
                        )
                        .where(ORMTask.started_at != None, ORMTask.ended_at == None, ORMTask.canceled_at == None)
                        .group_by(ORMTask.namespace_id)
                        .subquery()
                    )

                    # Subquery to find one eligible task_id that can be started
                    task_id_subquery = (
                        select(ORMTask.task_id)
                        .outerjoin(running_tasks_sub_query,
                                   ORMTask.namespace_id == running_tasks_sub_query.c.namespace_id)
                        .where(ORMTask.started_at == None)
                        .where(ORMTask.canceled_at == None)
                        .where(
                            func.coalesce(running_tasks_sub_query.c.running_count, 0) < ORMTask.concurrency_threshold)
                        .order_by(desc(ORMTask.priority), asc(ORMTask.created_at))
                        .limit(1)
                        .subquery()
                    )

                    # Actual query to lock the task row
                    stmt = (
                        select(ORMTask)
                        .where(ORMTask.task_id.in_(select(task_id_subquery.c.task_id)))
                        .with_for_update(skip_locked=True)
                    )

                    result = await session.execute(stmt)
                    orm_task = result.scalars().first()

                    if orm_task:
                        # Mark the task as started
                        orm_task.started_at = datetime.now()
                        session.add(orm_task)
                        task = Task.model_validate(orm_task)
                        await session.commit()
            except IntegrityError:  # Handle cases where the task was claimed by another worker
                await session.rollback()
            except Exception as e:
                self.logger.exception({
                    "error": CommonException.parse_exception(e)
                })
                await session.rollback()
            return task

    async def process_task(self, task: Task, trace_info: TraceInfo) -> Task:
        logging_func: Callable[[dict], None] = trace_info.info
        try:
            output = await self.worker_router(task, trace_info)
        except Exception as e:
            # Update the task with the exception details
            async with self.session_factory() as session:
                async with session.begin():
                    orm_task = await session.get(ORMTask, task.task_id)
                    orm_task.exception = {"error": CommonException.parse_exception(e)}
                    orm_task.ended_at = datetime.now()
                    session.add(orm_task)
                    await session.commit()

            logging_func = trace_info.bind(error=CommonException.parse_exception(e)).exception
        else:
            # Update the task with the result
            async with self.session_factory() as session:
                async with session.begin():
                    orm_task = await session.get(ORMTask, task.task_id)
                    orm_task.output = output
                    orm_task.ended_at = datetime.now()
                    session.add(orm_task)
                    await session.commit()
        logging_func(Task.model_validate(orm_task).model_dump(include={"created_at", "started_at", "ended_at"}))

        return Task.model_validate(orm_task)

    async def callback(self, task: Task, trace_info: TraceInfo):
        async with httpx.AsyncClient(base_url=self.config.backend.base_url) as client:
            http_response: httpx.Response = await client.post(
                f"/api/v1/tasks/callback",
                json=task.model_dump(exclude_none=True, mode="json"),
                headers={"X-Trace-ID": task.task_id}
            )
            logging_func: Callable[[dict], None] = trace_info.info if http_response.is_success else trace_info.error
            logging_func({"status_code": http_response.status_code, "response": http_response.json()})

    async def worker_router(self, task: Task, trace_info: TraceInfo) -> dict:
        function = task.function
        if function == "collect":
            worker = self.html_reader
        elif function == "create_or_update_index":
            worker = self.create_or_update_index
        elif function == "delete_index":
            worker = self.delete_index
        else:
            raise ValueError(f"Invalid function: {function}")
        return await worker.run(task, trace_info)
