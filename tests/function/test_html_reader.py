import json as jsonlib
import os
import pickle

import pytest
from dotenv import load_dotenv

from common import project_root
from common.trace_info import TraceInfo
from tests.helper.fixture import trace_info
from wizard.config import OpenAIConfig, ReaderConfig
from wizard.entity import Task
from wizard.wand.functions.html_reader import HTMLReader


@pytest.fixture(scope="function")
def reader_config() -> ReaderConfig:
    load_dotenv(dotenv_path=project_root.path(".env"))
    return ReaderConfig(
        openai=OpenAIConfig(
            api_key=os.environ["MBW_TASK_READER_OPENAI_API_KEY"],
            base_url=os.environ["MBW_TASK_READER_OPENAI_BASE_URL"],
            model=os.environ["MBW_TASK_READER_OPENAI_MODEL"],
        )
    )


@pytest.fixture(scope="function")
def task() -> Task:
    with project_root.open("tests/resources/tasks/tencent_news.pkl", "rb") as f:
        return pickle.load(f)


async def test_html_reader(reader_config: ReaderConfig, task: Task, trace_info: TraceInfo):
    c = HTMLReader(reader_config)
    result = await c.run(task, trace_info)
    print(jsonlib.dumps(result, ensure_ascii=False, separators=(",", ":")))
    # assert "Implement a notification system for updates and alerts." in result["markdown"]


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
