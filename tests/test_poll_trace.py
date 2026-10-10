import httpx
from opentelemetry.trace import StatusCode

from omnibox_wizard.worker.poll_trace import (
    EMPTY_POLL_ATTR,
    DropEmptyPollSpanProcessor,
    install_drop_empty_poll_processor,
    mark_empty_poll,
)


class _Inner:
    def __init__(self):
        self.ended = []

    def on_start(self, span, parent_context=None):
        return None

    def on_end(self, span):
        self.ended.append(span)

    def shutdown(self):
        return None

    def force_flush(self, timeout_millis=30000):
        return True


def _span(url, empty=False, error=False):
    attributes = {"http.url": url}
    if empty:
        attributes[EMPTY_POLL_ATTR] = True
    return type(
        "Span",
        (),
        {
            "attributes": attributes,
            "status": type(
                "Status",
                (),
                {"status_code": (StatusCode.ERROR if error else StatusCode.UNSET)},
            )(),
        },
    )()


class _Span:
    def __init__(self):
        self.attributes = {}

    def set_attribute(self, key, value):
        self.attributes[key] = value


def test_mark_empty_poll_only_for_null_task():
    empty = _Span()
    mark_empty_poll(empty, httpx.Response(200, json={"task": None}))
    assert empty.attributes[EMPTY_POLL_ATTR] is True

    claimed = _Span()
    mark_empty_poll(claimed, httpx.Response(200, json={"task": {"id": "1"}}))
    assert claimed.attributes == {}

    failed = _Span()
    mark_empty_poll(failed, httpx.Response(500, json={"task": None}))
    assert failed.attributes == {}


def test_processor_drops_only_empty_poll_spans():
    inner = _Inner()
    processor = DropEmptyPollSpanProcessor(inner)
    empty = _span("http://backend/internal/api/v1/wizard/tasks/poll", empty=True)
    claimed = _span("http://backend/internal/api/v1/wizard/tasks/poll")
    failed = _span(
        "http://backend/internal/api/v1/wizard/tasks/poll",
        empty=True,
        error=True,
    )
    other = _span("http://backend/internal/api/v1/wizard/callback", empty=True)

    processor.on_end(empty)
    processor.on_end(claimed)
    processor.on_end(failed)
    processor.on_end(other)

    assert inner.ended == [claimed, failed, other]


def test_install_wraps_existing_processor_once(monkeypatch):
    inner = _Inner()

    class _Multi:
        def __init__(self):
            self._span_processors = (inner,)
            self._lock = None

    multi = _Multi()

    class _Provider:
        _active_span_processor = multi

    monkeypatch.setattr(
        "omnibox_wizard.worker.poll_trace.trace.get_tracer_provider",
        lambda: _Provider(),
    )
    monkeypatch.setattr("omnibox_wizard.worker.poll_trace._installed", False)

    install_drop_empty_poll_processor()
    install_drop_empty_poll_processor()

    assert len(multi._span_processors) == 1
    assert isinstance(multi._span_processors[0], DropEmptyPollSpanProcessor)
    assert multi._span_processors[0]._inner is inner
