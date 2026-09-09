from types import SimpleNamespace

import pytest

from omnibox_wizard.worker.agent.html_tags_extractor import TagsExtractOutput
from omnibox_wizard.worker.functions.tag_extractor import TagExtractor
from wizard_common.worker.entity import Task


class FakeTagsExtractor:
    def __init__(self):
        self.input = None

    async def ainvoke(self, input_dict):
        self.input = input_dict
        return TagsExtractOutput(tags=["test"])


def make_task(input_dict):
    return Task(
        id="test_task",
        priority=1,
        namespace_id="test_namespace",
        user_id="test_user",
        function="extract_tags",
        input=input_dict,
    )


def make_tag_extractor(monkeypatch, tag_rules=""):
    async def fake_load(**kwargs):
        fake_load.calls.append(kwargs)
        return tag_rules

    fake_load.calls = []
    monkeypatch.setattr(
        "omnibox_wizard.worker.functions.tag_extractor.load_omnibox_markdown",
        fake_load,
    )
    tag_extractor = TagExtractor.__new__(TagExtractor)
    fake_extractor = FakeTagsExtractor()
    tag_extractor.tag_extractor = fake_extractor
    tag_extractor.config = SimpleNamespace(
        backend=SimpleNamespace(base_url="http://backend")
    )
    return tag_extractor, fake_extractor, fake_load


@pytest.mark.asyncio
async def test_tag_extractor_handles_missing_title(trace_info, monkeypatch):
    tag_extractor, fake_extractor, _ = make_tag_extractor(monkeypatch)

    result = await tag_extractor.run(make_task({"content": "123"}), trace_info)

    assert result == {"tags": ["test"]}
    assert fake_extractor.input == {"title": "", "snippet": "123", "lang": None}


@pytest.mark.asyncio
async def test_tag_extractor_passes_title_content_and_lang(trace_info, monkeypatch):
    tag_extractor, fake_extractor, fake_load = make_tag_extractor(monkeypatch)

    result = await tag_extractor.run(
        make_task({"title": "Title", "content": " Content ", "lang": "English"}),
        trace_info,
    )

    assert result == {"tags": ["test"]}
    assert fake_extractor.input == {
        "title": "Title",
        "snippet": "Content",
        "lang": "English",
    }
    assert fake_load.calls == [
        {
            "filename": "TAGS.md",
            "base_url": "http://backend",
            "namespace_id": "test_namespace",
            "user_id": "test_user",
        }
    ]


@pytest.mark.asyncio
async def test_tag_extractor_passes_tag_rules(trace_info, monkeypatch):
    tag_extractor, fake_extractor, _ = make_tag_extractor(
        monkeypatch, tag_rules="Use Work/Life tags"
    )

    result = await tag_extractor.run(make_task({"content": "123"}), trace_info)

    assert result == {"tags": ["test"]}
    assert fake_extractor.input["tag_rules"] == "Use Work/Life tags"


@pytest.mark.asyncio
async def test_tag_extractor_requires_content_or_title(trace_info, monkeypatch):
    tag_extractor, _, _ = make_tag_extractor(monkeypatch)

    with pytest.raises(ValueError, match="content or title is required"):
        await tag_extractor.run(make_task({}), trace_info)
