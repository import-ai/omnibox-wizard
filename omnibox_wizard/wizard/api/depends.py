from typing import Annotated

from fastapi import Header, Request
from opentelemetry import trace
from opentelemetry.propagate import extract

from omnibox_wizard.common.trace_info import TraceInfo


def get_trace_info(
        request: Request,
        x_request_id: Annotated[str | None, Header()] = None
) -> TraceInfo:
    """
    Extract trace context from incoming request headers and create TraceInfo
    """
    # Extract OpenTelemetry context from headers
    headers = dict(request.headers)
    context = extract(headers)

    # Get or create span from the extracted context
    span = None
    if context:
        # Set the context as current and get the span
        token = trace.set_span_in_context(trace.get_current_span(), context)
        with trace.use_span(trace.get_current_span()):
            span = trace.get_current_span()

    return TraceInfo(request_id=x_request_id, span=span)
