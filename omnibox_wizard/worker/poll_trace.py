import httpx
from opentelemetry import trace
from opentelemetry.sdk.trace import SpanProcessor
from opentelemetry.trace import StatusCode

EMPTY_POLL_ATTR = "omnibox.poll.empty"
POLL_PATH = "/internal/api/v1/wizard/tasks/poll"

_installed = False


class DropEmptyPollSpanProcessor(SpanProcessor):
    """Drops the httpx span for a 200 poll whose body is `{"task": null}`."""

    def __init__(self, inner: SpanProcessor):
        self._inner = inner

    def on_start(self, span, parent_context=None) -> None:
        self._inner.on_start(span, parent_context)

    def on_end(self, span) -> None:
        if _should_drop(span):
            return
        self._inner.on_end(span)

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


def install_drop_empty_poll_processor() -> None:
    global _installed
    if _installed:
        return
    provider = trace.get_tracer_provider()
    multi = getattr(provider, "_active_span_processor", None)
    processors = getattr(multi, "_span_processors", None)
    if not isinstance(processors, tuple):
        return
    wrapped = tuple(
        processor
        if isinstance(processor, DropEmptyPollSpanProcessor)
        else DropEmptyPollSpanProcessor(processor)
        for processor in processors
    )
    lock = getattr(multi, "_lock", None)
    if lock is None:
        multi._span_processors = wrapped
    else:
        with lock:
            multi._span_processors = wrapped
    _installed = True


class PollTraceTransport(httpx.AsyncHTTPTransport):
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await super().handle_async_request(request)
        if request.url.path == POLL_PATH and response.status_code == 200:
            await response.aread()
            mark_empty_poll(trace.get_current_span(), response)
        return response


def mark_empty_poll(span, response) -> None:
    if response.status_code != 200:
        return
    try:
        payload = response.json()
    except Exception:
        return
    if isinstance(payload, dict) and "task" in payload and payload["task"] is None:
        span.set_attribute(EMPTY_POLL_ATTR, True)


def _should_drop(span) -> bool:
    if span.attributes.get(EMPTY_POLL_ATTR) is not True:
        return False
    if span.status.status_code == StatusCode.ERROR:
        return False
    url = str(span.attributes.get("http.url") or span.attributes.get("url.full") or "")
    return POLL_PATH in url
