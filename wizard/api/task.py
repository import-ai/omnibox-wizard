from typing import Annotated

from fastapi import APIRouter, Depends, Body
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wizard.api.depends import get_trace_info
from wizard.common.exception import CommonException
from wizard.common.trace_info import TraceInfo
from wizard.db import engine, get_session
from wizard.db.entity import Base, Task


async def init():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


task_router = APIRouter(prefix="/task")


@task_router.post("")
async def create_task(
        task_dict: Annotated[dict, Body()],
        session: Annotated[AsyncSession, Depends(get_session)],
        trace_info: Annotated[TraceInfo, Depends(get_trace_info)]
):
    task = Task(**task_dict)
    session.add(task)
    await session.commit()
    await session.refresh(task)
    trace_info.info({"task_id": task.task_id})
    return JSONResponse({"task_id": task.task_id}, 201)


@task_router.get("")
async def list_tasks(
        session: Annotated[AsyncSession, Depends(get_session)],
        trace_info: Annotated[TraceInfo, Depends(get_trace_info)],
        offset: int = 0,
        limit: int = 10,
):
    result = await session.execute(select(Task).offset(offset).limit(limit))
    tasks = result.scalars().all()
    trace_info.info({"task_count": len(tasks)})
    return tasks


@task_router.get("/{task_id}")
async def get_task(task_id: str, session: Annotated[AsyncSession, Depends(get_session)]):
    result = await session.execute(select(Task).where(Task.task_id == task_id))
    task = result.scalar_one_or_none()

    if task is None:
        raise CommonException(404, f"Task {task_id} not found")
    return task


@task_router.delete("/{task_id}")
async def delete_task(
        task_id: str,
        session: Annotated[AsyncSession, Depends(get_session)],
        trace_info: Annotated[TraceInfo, Depends(get_trace_info)]
):
    result = await session.execute(select(Task).where(Task.task_id == task_id))
    task = result.scalar_one_or_none()

    if task is None:
        raise CommonException(404, f"Task {task_id} not found")

    await session.delete(task)
    await session.commit()

    trace_info.info({"task_id": task_id})
    return {"detail": "Task deleted"}
