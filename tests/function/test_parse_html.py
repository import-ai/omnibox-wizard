import json as jsonlib
import os
import pickle

import pytest
from dotenv import load_dotenv

from common import project_root
from common.trace_info import TraceInfo
from tests.helper.fixture import trace_info
from wizard.config import OpenAIConfig
from wizard.wand.functions.html_reader import HTMLReader
from wizard.wand.functions.html_to_markdown import HTMLToMarkdown


@pytest.fixture(scope="function")
def openai_config() -> OpenAIConfig:
    load_dotenv(dotenv_path=project_root.path(".env"))
    return OpenAIConfig(
        api_key=os.environ["MBW_TASK_READER_API_KEY"],
        base_url=os.environ["MBW_TASK_READER_BASE_URL"],
        model=os.environ["MBW_TASK_READER_MODEL"],
    )


async def test_parse_html(openai_config: OpenAIConfig, trace_info: TraceInfo):
    c = HTMLToMarkdown(openai_config)
    with project_root.open("tests/resources/task.pkl", "rb") as f:
        task = pickle.load(f)
    result = await c.run(task, trace_info)
    print(result)


async def test_html_reader(openai_config: OpenAIConfig, trace_info: TraceInfo):
    c = HTMLReader(openai_config)
    with project_root.open("tests/resources/task.pkl", "rb") as f:
        task = pickle.load(f)
    result = await c.run(task, trace_info)
    print(jsonlib.dumps(result, ensure_ascii=False, separators=(",", ":")))


async def test_html_clean(openai_config: OpenAIConfig):
    c = HTMLReader(openai_config)
    with project_root.open("tests/resources/input.json", "r") as f:
        input_dict: dict = jsonlib.load(f)
    html = input_dict["html"]
    print(f"raw length: {len(html)}")
    result = c.clean_html(html)
    print(f"cleaned length: {len(result)}")
    result = c.clean_html(html, clean_svg=True)
    print(f"after clean svg: {len(result)}")
    result = c.clean_html(html, clean_svg=True, clean_base64=True)
    print(f"after clean base64: {len(result)}")
    result = c.clean_html(html, clean_svg=True, clean_base64=True, remove_atts=True)
    print(f"after remove attributes: {len(result)}")
    result = c.clean_html(html, clean_svg=True, clean_base64=True, remove_atts=True, compress=True)
    print(f"after compress: {len(result)}")
    result = c.clean_html(html, clean_svg=True, clean_base64=True, remove_atts=True,
                          compress=True, remove_empty_tag=True)
    print(f"after remove empty tag: {len(result)}")
