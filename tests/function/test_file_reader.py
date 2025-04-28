import os

import pytest
from minio import Minio

from common import project_root
from tests.test_minio import client, bucket
from wizard.entity import Task
from wizard.wand.worker import Worker


@pytest.fixture(scope="function")
def file_url(client: Minio, bucket: str) -> str:
    basedir = project_root.path("tests/resources/files")
    filenames = [filename for filename in os.listdir(basedir)]
    filename = filenames[0]
    client.fput_object(bucket, os.path.join("task", filename), os.path.join(basedir, filename))
    return os.path.join("task", filename)


async def test_file_reader(worker: Worker, file_url: str):
    task: Task = Task(
        task_id="test",
        priority=5,

        namespace_id="test",
        user_id="test",

        function="file_reader",
        input={
            "url": file_url
        }
    )
    processed_task: Task = await worker.process_task(task, worker.get_trace_info(task))
    print(processed_task.output["markdown"])
