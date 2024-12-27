from typing import Annotated, List

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wizard.api.depends import get_trace_info, get_session
from wizard.common.exception import CommonException
from wizard.common.trace_info import TraceInfo
from wizard.db.entity import Task as ORMTask
from wizard.entity import Task

task_router = APIRouter(prefix="/tasks")


@task_router.post("", response_model=Task, response_model_include={"task_id"})
async def create_task(
        task: Task,
        session: Annotated[AsyncSession, Depends(get_session)],
        trace_info: Annotated[TraceInfo, Depends(get_trace_info)]
):
    orm_task = ORMTask(**task.model_dump())
    session.add(orm_task)
    await session.commit()
    trace_info.info({"task_id": orm_task.task_id})
    return JSONResponse(task.model_dump(include={"task_id"}), 201)


@task_router.get("", response_model=List[Task], response_model_exclude={"input", "output"},
                 response_model_exclude_none=True)
async def list_tasks(
        session: Annotated[AsyncSession, Depends(get_session)],
        trace_info: Annotated[TraceInfo, Depends(get_trace_info)],
        namespace_id: str,
        offset: int = 0,
        limit: int = 10,
):
    result = await session.execute(
        select(ORMTask).where(ORMTask.namespace_id == namespace_id).offset(offset).limit(limit))
    orm_task_list = result.scalars().all()
    trace_info.info({"task_count": len(orm_task_list), "namespace_id": namespace_id})
    task_list: List[Task] = []
    for orm_task in orm_task_list:
        task: Task = Task.model_validate(orm_task)
        task_list.append(task)
    return task_list


@task_router.get("/{task_id}", response_model=Task, response_model_exclude_none=True)
async def get_task(task_id: str, session: Annotated[AsyncSession, Depends(get_session)]):
    result = await session.execute(select(ORMTask).where(ORMTask.task_id == task_id))
    orm_task = result.scalar_one_or_none()

    if orm_task is None:
        raise CommonException(404, f"Task {task_id} not found")
    return Task.model_validate(orm_task)


@task_router.delete("/{task_id}")
async def delete_task(
        task_id: str,
        session: Annotated[AsyncSession, Depends(get_session)],
        trace_info: Annotated[TraceInfo, Depends(get_trace_info)]
):
    result = await session.execute(select(ORMTask).where(ORMTask.task_id == task_id))
    orm_task = result.scalar_one_or_none()

    if orm_task is None:
        raise CommonException(404, f"Task {task_id} not found")

    await session.delete(orm_task)
    await session.commit()

    trace_info.info({"task_id": task_id})
    return {"detail": "Task deleted"}
