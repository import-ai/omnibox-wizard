import pytest

from omnibox_wizard.common.trace_info import TraceInfo
from tests.omnibox_wizard.helper.fixture import trace_info, remote_config
from omnibox_wizard.wizard.config import Config
from omnibox_wizard.wizard.grimoire.common_ai import CommonAI

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


@pytest.mark.parametrize("text", text_list, ids=[
    "question-xiaoming",
    "weather-beijing", 
    "distance-sun-beijing",
    "health-milk-ice",
    "tech-markdown-mimetypes"
])
async def test_title(common_ai: CommonAI, trace_info: TraceInfo, text: str):
    title: str = await common_ai.title(text, trace_info=trace_info)
    print(title)


@pytest.mark.parametrize("text", text_list, ids=[
    "question-xiaoming",
    "weather-beijing",
    "distance-sun-beijing", 
    "health-milk-ice",
    "tech-markdown-mimetypes"
])
async def test_tags(common_ai: CommonAI, trace_info: TraceInfo, text: str):
    tags: list[str] = await common_ai.tags(text, trace_info=trace_info)
    print(tags)


# Test cases for lang parameter functionality

@pytest.mark.parametrize("text,lang,expected_type", [
    ("小明是谁？", "简体中文", str),
    ("What's AI?", "English", str),
    ("今天北京的天气", "繁體中文", str),
    ("Qu'est-ce que l'IA?", "Français", str),
], ids=[
    "chinese-simplified-question",
    "english-ai-question",
    "chinese-traditional-weather",
    "french-ai-question"
])
async def test_title_with_lang_parameter(common_ai: CommonAI, trace_info: TraceInfo, text: str, lang: str, expected_type: type):
    """Test title generation with different language parameters"""
    title: str = await common_ai.title(text, lang=lang, trace_info=trace_info)
    assert isinstance(title, expected_type)
    assert len(title) > 0
    print(f"Text: {text} | Lang: {lang} | Title: {title}")


@pytest.mark.parametrize("text,lang,expected_type", [
    ("小明是谁？", "简体中文", list),
    ("What's AI?", "English", list),
    ("今天北京的天气", "繁體中文", list),
    ("Qu'est-ce que l'IA?", "Français", list),
], ids=[
    "chinese-simplified-question",
    "english-ai-question", 
    "chinese-traditional-weather",
    "french-ai-question"
])
async def test_tags_with_lang_parameter(common_ai: CommonAI, trace_info: TraceInfo, text: str, lang: str, expected_type: type):
    """Test tags generation with different language parameters"""
    tags: list[str] = await common_ai.tags(text, lang=lang, trace_info=trace_info)
    assert isinstance(tags, expected_type)
    assert len(tags) > 0
    assert all(isinstance(tag, str) for tag in tags)
    print(f"Text: {text} | Lang: {lang} | Tags: {tags}")


async def test_title_default_lang(common_ai: CommonAI, trace_info: TraceInfo):
    """Test title generation with default language (简体中文)"""
    text = "人工智能是什么？"
    title: str = await common_ai.title(text, trace_info=trace_info)
    assert isinstance(title, str)
    assert len(title) > 0
    print(f"Default lang title: {title}")


async def test_tags_default_lang(common_ai: CommonAI, trace_info: TraceInfo):
    """Test tags generation with default language (简体中文)"""
    text = "人工智能是什么？"
    tags: list[str] = await common_ai.tags(text, trace_info=trace_info)
    assert isinstance(tags, list)
    assert len(tags) > 0
    assert all(isinstance(tag, str) for tag in tags)
    print(f"Default lang tags: {tags}")


@pytest.mark.parametrize("text", [
    "机器学习和深度学习的区别",
    "What is the difference between machine learning and deep learning?",
    "機器學習和深度學習的區別",
], ids=[
    "ml-dl-difference-simplified",
    "ml-dl-difference-english", 
    "ml-dl-difference-traditional"
])
async def test_multilingual_consistency(common_ai: CommonAI, trace_info: TraceInfo, text: str):
    """Test that different language settings produce consistent results for similar content"""
    # Test with Chinese
    title_zh = await common_ai.title(text, lang="简体中文", trace_info=trace_info)
    tags_zh = await common_ai.tags(text, lang="简体中文", trace_info=trace_info)
    
    # Test with English
    title_en = await common_ai.title(text, lang="English", trace_info=trace_info)
    tags_en = await common_ai.tags(text, lang="English", trace_info=trace_info)
    
    # Both should return valid results
    assert isinstance(title_zh, str) and len(title_zh) > 0
    assert isinstance(title_en, str) and len(title_en) > 0
    assert isinstance(tags_zh, list) and len(tags_zh) > 0
    assert isinstance(tags_en, list) and len(tags_en) > 0
    
    print(f"Text: {text}")
    print(f"Chinese - Title: {title_zh}, Tags: {tags_zh}")
    print(f"English - Title: {title_en}, Tags: {tags_en}")


async def test_edge_case_empty_lang(common_ai: CommonAI, trace_info: TraceInfo):
    """Test behavior with empty language parameter"""
    text = "测试文本"
    # Should use default lang when empty string is passed
    title = await common_ai.title(text, lang="", trace_info=trace_info)
    tags = await common_ai.tags(text, lang="", trace_info=trace_info)
    
    assert isinstance(title, str)
    assert isinstance(tags, list)
    print(f"Empty lang - Title: {title}, Tags: {tags}")
