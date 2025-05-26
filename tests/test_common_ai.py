import pytest

from common.trace_info import TraceInfo
from tests.helper.fixture import trace_info, remote_config
from wizard.config import Config
from wizard.grimoire.common_ai import CommonAI


@pytest.fixture(scope='function')
def common_ai(remote_config: Config) -> CommonAI:
    return CommonAI(remote_config.grimoire.openai)


@pytest.mark.parametrize("text", [
    "小明是谁？",
    "今天北京的天气",
    "太阳到北京的距离",
    "牛奶加冰会拉肚子吗",
    "What's the different between `text/x-markdown` and `text/markdown` in mimetypes?",
])
async def test_title(common_ai: CommonAI, trace_info: TraceInfo, text: str):
    title: str = await common_ai.title(text, trace_info=trace_info)
    print(title)
