import json as jsonlib
import os

import pandas as pd
import pytest

from common import project_root
from common.trace_info import TraceInfo
from tests.omnibox_wizard.helper.get_task_by_id import get_task_by_id
from wizard_common.worker.entity import Task
from omnibox_wizard.worker.functions.html_reader.html_reader import HTMLReaderV2
from tests.omnibox_wizard.helper.get_collect_html import get_collect_html
from dotenv import load_dotenv

from omnibox_wizard.worker.config import WorkerConfig

load_dotenv()


def get_tasks() -> list[Task]:
    tasks = []
    try:
        csv_path: str = "tests/omnibox_wizard/resources/files/tasks.csv"
        df = pd.read_csv(project_root.path(csv_path))
        for _, row in df.iterrows():
            task = Task(
                id=row["id"],
                priority=5,
                namespace_id="test",
                user_id="test",
                function="collect",
                input=jsonlib.loads(row["input"]),
            )
            tasks.append(task)
    except Exception:
        pass
    return tasks


html_reader_base_dir = "tests/omnibox_wizard/resources/files/html_reader_input"


async def process_task(task: Task, trace_info: TraceInfo, remote_worker_config):
    c = HTMLReaderV2(remote_worker_config)
    print(task.input["url"])
    if task.input["html"].startswith("collect/html/gzip/"):
        path = task.input["html"]
        task.input["html"] = get_collect_html(path)
    result = await c.run(task, trace_info)
    print(jsonlib.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return result


def list_dir():
    try:
        return os.listdir(project_root.path(html_reader_base_dir))
    except Exception:
        return []


@pytest.mark.parametrize(
    "filename",
    filter(
        lambda x: x.endswith(".json"),
        list_dir(),
    ),
)
async def test_html_reader_v2(
    filename: str, trace_info: TraceInfo, remote_worker_config
):
    with project_root.open(os.path.join(html_reader_base_dir, filename)) as f:
        task = Task(
            id=filename,
            priority=5,
            namespace_id="test",
            user_id="test",
            function="collect",
            input=jsonlib.load(f),
        )
    result = await process_task(task, trace_info, remote_worker_config)
    print("=" * 32)
    print("# " + result["title"] + "\n\n" + result["markdown"])


@pytest.mark.parametrize("task", get_tasks())
async def test_html_reader_by_csv(
    task: Task, trace_info: TraceInfo, remote_worker_config
):
    result = await process_task(task, trace_info, remote_worker_config)
    print("=" * 32)
    print("# " + result["title"] + "\n\n" + result["markdown"])


@pytest.mark.parametrize("task_id", os.getenv("OBW_TEST_TASK_IDS", "").split(","))
async def test_html_reader_by_task_id(
    task_id: str, trace_info: TraceInfo, remote_worker_config: WorkerConfig
):
    task: Task = await get_task_by_id(task_id)
    result = await process_task(task, trace_info, remote_worker_config)
    print("=" * 32)
    print("# " + result["title"] + "\n\n" + result["markdown"])
