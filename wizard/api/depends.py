from typing import Annotated

from fastapi import Header

from wizard.common.trace_info import TraceInfo


def get_trace_info(trace_id: Annotated[str | None, Header()] = None) -> TraceInfo:
    return TraceInfo(trace_id=trace_id)
