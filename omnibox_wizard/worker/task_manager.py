import asyncio
from typing import Callable, Any

from opentelemetry import trace

from common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from wizard_common.worker.entity import Task

tracer = trace.get_tracer(__name__)


class TaskManager:
    """Manages task lifecycle including timeout handling."""

    def __init__(self, config: WorkerConfig):
        self.config = config

    @tracer.start_as_current_span("TaskManager.run_with_timeout")
    async def run_with_timeout(
        self,
        task: Task,
        execution_func: Callable[[Task, TraceInfo], Any],
        trace_info: TraceInfo,
    ) -> Any:
        """Run a task with timeout support."""
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
            }
        )

        # Create the main execution task
        execution_task = asyncio.create_task(execution_func(task, trace_info))

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
