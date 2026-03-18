import os
from urllib.parse import urlparse

from opentelemetry import trace

from common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.functions.base_function import BaseFunction
from wizard_common.worker.entity import Task, TaskFunction

tracer = trace.get_tracer(__name__)


def is_xhs(url: str) -> bool:
    domain: str = urlparse(url).netloc
    for pattern in ["xiaohongshu.com", "xhslink.com"]:
        if pattern in domain:
            return True
    return False


class WebAnalysisFunction(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.video_prefixes: list[str] = list(
            filter(bool, os.getenv("OB_VIDEO_PREFIXES", "").split(","))
        )

    def is_video(self, url: str, html: str) -> bool:
        for prefix in self.video_prefixes:
            if url.startswith(prefix):
                return True

        if is_xhs(url) and '"type":"video"' in html:
            return True
        return False

    @tracer.start_as_current_span("WebAnalysisFunction.run")
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        span = trace.get_current_span()
        url = task.input["url"]
        html = task.input["html"]
        title = task.input.get("title", "")

        span.set_attribute("url", url)

        is_video = self.is_video(url, html)
        span.set_attribute("is_video", is_video)

        return {
            "is_video": is_video,
            "next_tasks": [
                task.create_next_task(
                    TaskFunction.GENERATE_VIDEO_NOTE
                    if is_video
                    else TaskFunction.COLLECT,
                    {"url": url, "html": html, "title": title},
                ).model_dump()
            ],
        }
