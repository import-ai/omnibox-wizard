import asyncio
from datetime import datetime
from typing import Optional

from sqlalchemy import select, func, desc, asc
from sqlalchemy.exc import IntegrityError

from wizard.common.exception import CommonException
from wizard.db import get_session
from wizard.db.entity import Task, NamespaceConfig
from wizard.worker import HTMLToMarkdown


class Worker:
    def __init__(self, worker_id: int):
        self.worker_id = worker_id
        self.html_to_markdown = HTMLToMarkdown()

    async def run(self):
        while True:
            task = await self.fetch_and_claim_task()
            if task:
                print(f"Worker {self.worker_id}: Processing task {task.task_id} for namespace {task.namespace_id}")
                await self.process_task(task)
            else:
                # No available task, wait before retrying
                await asyncio.sleep(1)

    async def fetch_and_claim_task(self) -> Optional[Task]:
        async with get_session() as session:
            try:
                async with session.begin():
                    # Subquery to count running tasks per user
                    running_tasks_sub_query = (
                        select(
                            Task.namespace_id,
                            func.count(Task.task_id).label('running_count')
                        )
                        .where(Task.start_time != None, Task.end_time == None, Task.cancel_time == None)
                        .group_by(Task.namespace_id)
                        .subquery()
                    )

                    # Select one task that can be started
                    stmt = (
                        select(Task)
                        .join(NamespaceConfig, Task.namespace_config == NamespaceConfig.namespace_id)
                        .outerjoin(running_tasks_sub_query, Task.namespace_id == running_tasks_sub_query.c.namespace_id)
                        .where(Task.start_time == None)
                        .where(Task.cancel_time == None)
                        .where(
                            func.coalesce(running_tasks_sub_query.c.running_count, 0) < NamespaceConfig.max_concurrency)
                        .order_by(desc(Task.priority), asc(Task.create_time))
                        .with_for_update(skip_locked=True)
                        .limit(1)
                    )

                    result = await session.execute(stmt)
                    task = result.scalars().first()

                    if task:
                        # Mark the task as started
                        task.start_time = datetime.now()
                        session.add(task)
                        await session.commit()
                        return task
            except IntegrityError:  # Handle cases where the task was claimed by another worker
                await session.rollback()
            except Exception as e:
                print(f"Worker {self.worker_id}: Encountered an error: {e}")
                await session.rollback()
            return None

    async def process_task(self, task: Task):
        try:
            # Placeholder for actual processing logic
            output = await self.call(task.function, task.input)

            # Update the task with the result
            async with get_session() as session:
                async with session.begin():
                    db_task = await session.get(Task, task.task_id)
                    db_task.output = output
                    db_task.end_time = datetime.now()
                    session.add(db_task)
                    await session.commit()
            print(f"Worker {self.worker_id}: Completed task {task.task_id}")
        except Exception as e:
            # Update the task with the exception details
            async with get_session() as session:
                async with session.begin():
                    db_task = await session.get(Task, task.task_id)
                    db_task.exception = {"error": CommonException.parse_exception(e)}
                    db_task.end_time = datetime.now()
                    session.add(db_task)
                    await session.commit()
            print(
                f"Worker {self.worker_id}: Failed task {task.task_id} with error: {CommonException.parse_exception(e)}")

    async def call(self, function: str, input_data: dict) -> dict:
        if function == "html_to_markdown":
            worker = self.html_to_markdown
        else:
            raise ValueError(f"Invalid function: {function}")
        return await worker.run(input_data)
