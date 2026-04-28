from opentelemetry import trace

from common.trace_info import TraceInfo
from omnibox_wizard.worker.agent.html_title_extractor import (
    HTMLTitleExtractOutput,
    HTMLTitleExtractor,
)
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.functions.base_function import BaseFunction
from wizard_common.worker.entity import Task

tracer = trace.get_tracer("TitleGenerator")


class TitleGenerator(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.html_title_extractor = HTMLTitleExtractor(config.grimoire.openai)

    @tracer.start_as_current_span("TitleGenerator.get_title")
    async def get_title(
        self, markdown: str, raw_title: str, trace_info: TraceInfo
    ) -> str:
        span = trace.get_current_span()
        try:
            snippet: str = markdown.strip()[:512]
            title_extract_output: HTMLTitleExtractOutput = (
                await self.html_title_extractor.ainvoke(
                    {"title": raw_title, "snippet": snippet}, trace_info
                )
            )
            return title_extract_output.title
        except Exception as e:
            span.record_exception(e)
            return raw_title

    @tracer.start_as_current_span("TitleGenerator.run")
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        span = trace.get_current_span()
        input_dict = task.input
        raw_title = input_dict.get("title", "")
        content = input_dict.get("content", "")

        if (not raw_title) and (not content):
            raise ValueError("Text input is required for title generation")

        trace_info = trace_info.bind(text_length=len(content))
        trace_info.info({"message": "Starting title generation"})

        title = await self.get_title(content, raw_title, trace_info)
        span.set_attributes(
            {
                "raw_title": raw_title,
                "title": title,
            }
        )

        result_dict = {"title": title}
        trace_info.info(
            {"generated_title": title, "message": "Title generation completed"}
        )
        return result_dict
