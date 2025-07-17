import json as jsonlib
import os

import pytest

from omnibox_wizard.common import project_root
from omnibox_wizard.common.trace_info import TraceInfo
from tests.omnibox_wizard.helper.fixture import trace_info
from omnibox_wizard.wizard.entity import Task
from omnibox_wizard.wizard.wand.functions import HTMLReaderV2

html_reader_base_dir = "tests/resources/files/html_reader_input"


@pytest.mark.parametrize("filename", filter(
    lambda x: x.endswith('.json'),
    os.listdir(project_root.path(html_reader_base_dir))
))
async def test_html_reader_v2(filename: str, trace_info: TraceInfo):
    with project_root.open(os.path.join(html_reader_base_dir, filename)) as f:
        task = Task(
            id=filename,
            priority=5,
            namespace_id='test',
            user_id='test',
            function="collect",
            input=jsonlib.load(f)
        )
    c = HTMLReaderV2()
    print(task.input['url'])
    result = await c.run(task, trace_info)
    print(jsonlib.dumps(result, ensure_ascii=False, separators=(",", ":")))
    with project_root.open(os.path.join(html_reader_base_dir, filename.replace(".json", ".md")), "w") as f:
        f.write(result["markdown"])
