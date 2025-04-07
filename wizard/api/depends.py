from typing import Annotated

from fastapi import Header

from common.trace_info import TraceInfo


def get_trace_info(x_trace_id: Annotated[str | None, Header()] = None) -> TraceInfo:
    return TraceInfo(trace_id=x_trace_id)
