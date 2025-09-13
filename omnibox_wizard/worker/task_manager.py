import asyncio
from typing import Optional, Callable, Any

import httpx
from opentelemetry import trace

from omnibox_wizard.common.exception import CommonException
from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task

tracer = trace.get_tracer(__name__)


class TaskManager:
    """Manages task lifecycle including timeout and cancellation handling."""

    def __init__(self, config: WorkerConfig):
        self.config = config

    async def check_task_status(self, task_id: str, trace_info: TraceInfo) -> Optional[Task]:
        """Fetch task from backend to check its current status."""
        try:
            async with httpx.AsyncClient(base_url=self.config.backend.base_url) as client:
                response = await client.get(f"internal/api/v1/wizard/tasks/{task_id}")
                if response.is_success:
                    return Task.model_validate(response.json())
                else:
                    trace_info.warning({
                        "message": "Failed to fetch task status",
                        "task_id": task_id,
                        "status_code": response.status_code
                    })
        except Exception as e:
            trace_info.exception({
                "message": "Error checking task status",
                "task_id": task_id,
                "error": CommonException.parse_exception(e)
            })
        return None

    async def monitor_cancellation(self, task_id: str, execution_task: asyncio.Task, trace_info: TraceInfo):
        """Monitor task cancellation status and cancel execution if needed."""
        check_interval = self.config.task.cancellation_check_interval

        while not execution_task.done():
            try:
                task_status = await self.check_task_status(task_id, trace_info)
                if task_status and task_status.canceled_at:
                    trace_info.info({
                        "message": "Task cancellation detected, cancelling execution",
                        "task_id": task_id,
                        "canceled_at": task_status.canceled_at.isoformat()
                    })
                    execution_task.cancel()
                    break

                await asyncio.sleep(check_interval)
            except Exception as e:
                trace_info.exception({
                    "message": "Error in cancellation monitor",
                    "task_id": task_id,
                    "error": CommonException.parse_exception(e)
                })
                # Continue monitoring even if there's an error
                await asyncio.sleep(check_interval)

    @tracer.start_as_current_span("TaskManager.run_with_timeout_and_cancellation")
    async def run_with_timeout_and_cancellation(
            self,
            task: Task,
            execution_func: Callable[[Task, TraceInfo], Any],
            trace_info: TraceInfo
    ) -> Any:
        """Run a task with both timeout and cancellation support."""
        span = trace.get_current_span()
        task_timeout = self.config.task.timeout

        span.set_attributes({
            "task.id": task.id,
            "task.timeout": task_timeout,
            "task.cancellation_check_interval": self.config.task.cancellation_check_interval
        })

        # Create the main execution task
        execution_task = asyncio.create_task(execution_func(task, trace_info))

        # Create the cancellation monitor task
        monitor_task = asyncio.create_task(
            self.monitor_cancellation(task.id, execution_task, trace_info)
        )

        try:
            # Wait for execution with timeout
            result = await asyncio.wait_for(execution_task, timeout=task_timeout)
            span.set_attribute("task.completed_successfully", True)
            return result

        except asyncio.TimeoutError:
            trace_info.warning({
                "message": "Task execution timeout",
                "task_id": task.id,
                "timeout": task_timeout
            })
            span.set_attribute("task.timeout_occurred", True)
            # Cancel the execution task if it's still running
            if not execution_task.done():
                execution_task.cancel()
            raise

        except asyncio.CancelledError:
            trace_info.info({
                "message": "Task execution cancelled",
                "task_id": task.id
            })
            span.set_attribute("task.cancelled", True)
            raise

        finally:
            # Clean up the monitor task
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
