import json as jsonlib
import os

import pytest
from dotenv import load_dotenv

from common import project_root
from common.trace_info import TraceInfo
from tests.helper.fixture import trace_info
from wizard.config import OpenAIConfig, ReaderConfig
from wizard.entity import Task
from wizard.wand.functions.html_reader import HTMLReader, HTMLReaderV2


@pytest.fixture(scope="function")
def reader_config() -> ReaderConfig:
    load_dotenv(dotenv_path=project_root.path(".env"))
    return ReaderConfig(
        openai=OpenAIConfig(
            api_key=os.environ["OBW_TASK_READER_OPENAI_API_KEY"],
            base_url=os.environ["OBW_TASK_READER_OPENAI_BASE_URL"],
            model=os.environ["OBW_TASK_READER_OPENAI_MODEL"],
        )
    )


html_reader_base_dir = "tests/resources/files/html_reader_input"


@pytest.mark.parametrize("filename", os.listdir(project_root.path(html_reader_base_dir)))
async def test_html_reader(filename: str, reader_config: ReaderConfig, trace_info: TraceInfo):
    with project_root.open(os.path.join(html_reader_base_dir, filename)) as f:
        task = Task(
            id=filename,
            priority=5,
            namespace_id='test',
            user_id='test',
            function="collect",
            input=jsonlib.load(f)
        )
    c = HTMLReader(reader_config)
    print(task.input['url'])
    result = await c.run(task, trace_info)
    print(jsonlib.dumps(result, ensure_ascii=False, separators=(",", ":")))


@pytest.mark.parametrize("filename", filter(
    lambda x: x.endswith('.json'),
    os.listdir(project_root.path(html_reader_base_dir))
))
async def test_html_reader_v2(filename: str, reader_config: ReaderConfig, trace_info: TraceInfo):
    with project_root.open(os.path.join(html_reader_base_dir, filename)) as f:
        task = Task(
            id=filename,
            priority=5,
            namespace_id='test',
            user_id='test',
            function="collect",
            input=jsonlib.load(f)
        )
    c = HTMLReaderV2(reader_config)
    print(task.input['url'])
    result = await c.run(task, trace_info)
    print(jsonlib.dumps(result, ensure_ascii=False, separators=(",", ":")))
    with project_root.open(os.path.join(html_reader_base_dir, filename.replace(".json", ".md")), "w") as f:
        f.write(result["markdown"])


async def test_html_clean(reader_config: ReaderConfig, task: Task):
    c = HTMLReader(reader_config)
    html = task.input["html"]
    url = task.input["url"]
    print(f"raw length: {len(html)}")
    result = c.clean_html(url, html)
    print(f"cleaned length: {len(result)}")
    result = c.clean_html(url, html, clean_svg=True)
    print(f"after clean svg: {len(result)}")
    result = c.clean_html(url, html, clean_svg=True, clean_base64=True)
    print(f"after clean base64: {len(result)}")
    result = c.clean_html(url, html, clean_svg=True, clean_base64=True, remove_atts=True)
    print(f"after remove attributes: {len(result)}")
    result = c.clean_html(url, html, clean_svg=True, clean_base64=True, remove_atts=True, compress=True)
    print(f"after compress: {len(result)}")
    result = c.clean_html(url, html, clean_svg=True, clean_base64=True, remove_atts=True,
                          compress=True, remove_empty_tag=True)
    print(f"after remove empty tag: {len(result)}")
    result = c.clean_html(url, html, clean_svg=True, clean_base64=True, remove_atts=True,
                          compress=True, remove_empty_tag=True, enable_content_selector=True)
    print(f"after content selector: {len(result)}")
