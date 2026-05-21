from types import SimpleNamespace

from common.exception import CommonException
from common.trace_info import TraceInfo
from omnibox_wizard.worker.worker import Worker
from wizard_common.worker.entity import Task


async def test_worker_preserves_common_exception_code(trace_info: TraceInfo):
    class TooLongFileReader:
        async def run(self, task, trace_info):
            raise CommonException(
                "FILE_CONTENT_TOO_LONG",
                "The current file content exceeds the system processing limit.",
            )

    worker = object.__new__(Worker)
    worker.worker_dict = {"file_reader": TooLongFileReader()}
    worker.config = SimpleNamespace(
        task=SimpleNamespace(
            function_timeouts=SimpleNamespace(get_timeout=lambda _function: None),
            timeout=300,
        )
    )
    worker.task_manager = SimpleNamespace(
        run_with_timeout_and_cancellation=lambda task, router, trace_info: router(
            task, trace_info
        )
    )
    task = Task(
        id="test",
        priority=5,
        namespace_id="test",
        user_id="test",
        function="file_reader",
        input={"language": "en-US"},
    )

    processed_task = await worker.process_task(task, trace_info)

    assert processed_task.status == "error"
    assert processed_task.output is None
    assert processed_task.exception is not None
    assert processed_task.exception["code"] == "FILE_CONTENT_TOO_LONG"
    assert processed_task.exception["error"] == (
        "The current file content exceeds the system processing limit."
    )
