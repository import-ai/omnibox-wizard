import asyncio
from typing import Callable, Any

import httpx
from opentelemetry import trace

from common.exception import CommonException
from common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from wizard_common.worker.entity import Task

tracer = trace.get_tracer(__name__)


class TaskManager:
    """Manages task lifecycle including timeout and cancellation handling."""

    def __init__(self, config: WorkerConfig):
        self.config = config

    async def check_task_status(self, task_id: str) -> Task:
        """Fetch task from backend to check its current status."""
        async with httpx.AsyncClient(base_url=self.config.backend.base_url) as client:
            response = await client.get(f"/internal/api/v1/wizard/tasks/{task_id}")
            response.raise_for_status()
            return Task.model_validate(response.json())

    async def monitor_cancellation(
        self, task_id: str, execution_task: asyncio.Task, trace_info: TraceInfo
    ):
        """Monitor task cancellation status and cancel execution if needed."""
        check_interval = self.config.task.cancellation_check_interval

        while not execution_task.done():
            try:
                task = await self.check_task_status(task_id)
                if task.canceled_at:
                    trace_info.info(
                        {
                            "message": "Task cancellation detected, cancelling execution",
                            "task_id": task_id,
                            "canceled_at": task.canceled_at.isoformat(),
                        }
                    )
                    execution_task.cancel()
                    break

                await asyncio.sleep(check_interval)
            except Exception as e:
                trace_info.warning(
                    {
                        "message": "Error in cancellation monitor",
                        "task_id": task_id,
                        "error": CommonException.parse_exception(e),
                    }
                )
                # Continue monitoring even if there's an error
                await asyncio.sleep(check_interval)

    @tracer.start_as_current_span("TaskManager.run_with_timeout_and_cancellation")
    async def run_with_timeout_and_cancellation(
        self,
        task: Task,
        execution_func: Callable[[Task, TraceInfo], Any],
        trace_info: TraceInfo,
    ) -> Any:
        """Run a task with both timeout and cancellation support."""
        span = trace.get_current_span()

        # Get function-specific timeout if configured, otherwise use global timeout
        function_timeout = self.config.task.function_timeouts.get_timeout(task.function)
        task_timeout = (
            function_timeout
            if function_timeout is not None
            else self.config.task.timeout
        )

        span.set_attributes(
            {
                "task.id": task.id,
                "task.function": task.function,
                "task.timeout": task_timeout,
                "task.timeout_source": "function_specific"
                if function_timeout is not None
                else "global",
                "task.cancellation_check_interval": self.config.task.cancellation_check_interval,
            }
        )

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
            trace_info.warning(
                {
                    "message": "Task execution timeout",
                    "task_id": task.id,
                    "timeout": task_timeout,
                }
            )
            span.set_attribute("task.timeout_occurred", True)
            # Cancel the execution task if it's still running
            if not execution_task.done():
                execution_task.cancel()
            raise

        except asyncio.CancelledError:
            trace_info.info({"message": "Task execution cancelled", "task_id": task.id})
            span.set_attribute("task.cancelled", True)
            raise

        finally:
            # Clean up the monitor task
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
