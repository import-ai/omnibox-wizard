import json as jsonlib
import os

import pytest

from omnibox_wizard.common import project_root
from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.functions.html_reader import HTMLReaderV2
from tests.omnibox_wizard.helper.fixture import trace_info, remote_worker_config

html_reader_base_dir = "tests/omnibox_wizard/resources/files/html_reader_input"


@pytest.mark.parametrize("filename", filter(
    lambda x: x.endswith('.json'),
    os.listdir(project_root.path(html_reader_base_dir))
))
async def test_html_reader_v2(filename: str, trace_info: TraceInfo, remote_worker_config):
    with project_root.open(os.path.join(html_reader_base_dir, filename)) as f:
        task = Task(
            id=filename,
            priority=5,
            namespace_id='test',
            user_id='test',
            function="collect",
            input=jsonlib.load(f)
        )
    c = HTMLReaderV2(remote_worker_config)
    print(task.input['url'])
    result = await c.run(task, trace_info)
    print(jsonlib.dumps(result, ensure_ascii=False, separators=(",", ":")))
    with project_root.open(os.path.join(html_reader_base_dir, filename.replace(".json", ".md")), "w") as f:
        f.write("# " + result["title"] + "\n\n" + result["markdown"])
