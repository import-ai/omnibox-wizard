import pytest
from unittest.mock import AsyncMock
from common.trace_info import TraceInfo
from omnibox_wizard.worker.functions.html_reader.html_reader import (
    HTMLReaderV2,
    has_web_body,
)
from wizard_common.worker.entity import Task


@pytest.mark.parametrize(
    ("markdown", "title", "expected"),
    [
        ("# Title", "Title", False),
        ("Title", "Title", False),
        ("Title\n=====", "Title", False),
        ("Title\n-----", "Title", False),
        ("# Title\n\nA real body", "Title", True),
        ("A short body", "Title", True),
        ("![photo](https://example.com/image.png)", "Title", True),
    ],
)
def test_body_boundary(markdown, title, expected):
    assert has_web_body(markdown, title) is expected


@pytest.mark.asyncio
async def test_title_only_producer_never_dispatches_billable_body(monkeypatch):
    import omnibox_wizard.worker.functions.html_reader.html_reader as module

    monkeypatch.setattr(module, "check_task_quota", AsyncMock(return_value={}))
    reader = object.__new__(HTMLReaderV2)
    reader.backend_base_url = "http://unused.invalid"
    reader.main = AsyncMock(return_value={"title": "Title", "markdown": "# Title"})
    task = Task.model_construct(
        id="test", input={"url": "https://example.com"}, payload={}
    )
    with pytest.raises(RuntimeError, match="NO_DELIVERABLE_CONTENT"):
        await reader.run(task, TraceInfo())
