from opentelemetry import trace

from common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.worker.functions.collect_url import CollectUrlFunction
from omnibox_wizard.worker.functions.html_reader.html_reader import HTMLReaderV2
from wizard_common.worker.entity import Task

tracer = trace.get_tracer(__name__)


class RssItemParserFunction(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.collect_url = CollectUrlFunction(config)
        self.html_reader = HTMLReaderV2(config)

    @tracer.start_as_current_span("RssItemParserFunction.run")
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        url = task.input["url"]
        if not url:
            raise ValueError("RSS item URL is required")

        scrape_result = await self.collect_url._scrape_url(url)
        reader_task = task.model_copy(
            update={
                "input": {
                    "url": scrape_result.final_url,
                    "html": scrape_result.html,
                    "title": scrape_result.title,
                }
            }
        )
        result = await self.html_reader.main(reader_task, trace_info)
        return {"markdown": result.get("markdown", "")}
