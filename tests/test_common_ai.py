import pytest

from omnibox.common.trace_info import TraceInfo
from tests.helper.fixture import trace_info, remote_config
from omnibox.wizard.config import Config
from omnibox.wizard.grimoire.common_ai import CommonAI

text_list: list[str] = [
    "小明是谁？",
    "今天北京的天气",
    "太阳到北京的距离",
    "牛奶加冰会拉肚子吗",
    "What's the different between `text/x-markdown` and `text/markdown` in mimetypes?",
]


@pytest.fixture(scope='function')
def common_ai(remote_config: Config) -> CommonAI:
    return CommonAI(remote_config.grimoire.openai)


@pytest.mark.parametrize("text", text_list)
async def test_title(common_ai: CommonAI, trace_info: TraceInfo, text: str):
    title: str = await common_ai.title(text, trace_info=trace_info)
    print(title)


@pytest.mark.parametrize("text", text_list)
async def test_title(common_ai: CommonAI, trace_info: TraceInfo, text: str):
    tags: list[str] = await common_ai.tags(text, trace_info=trace_info)
    print(tags)
