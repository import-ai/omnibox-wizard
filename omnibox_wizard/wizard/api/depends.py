from typing import Annotated

from fastapi import Header

from omnibox_wizard.common.trace_info import TraceInfo


def get_trace_info(x_request_id: Annotated[str | None, Header()] = None) -> TraceInfo:
    return TraceInfo(request_id=x_request_id)
