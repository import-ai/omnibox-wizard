from opentelemetry import trace

from common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.functions.collect_url import CollectUrlFunction
from omnibox_wizard.worker.functions.html_reader.html_reader import HTMLReaderV2
from wizard_common.worker.entity import Task

tracer = trace.get_tracer(__name__)


class RssItemParser:
    """Scrapes an RSS item's article URL and renders it to Markdown.

    Invoked synchronously by the internal RSS parse API; it deliberately skips
    the media analysis, tagging and title steps that the collect task chains on.
    """

    def __init__(self, config: WorkerConfig):
        self.collect_url = CollectUrlFunction(config)
        self.html_reader = HTMLReaderV2(config)

    @tracer.start_as_current_span("RssItemParser.parse")
    async def parse(self, url: str, trace_info: TraceInfo) -> str:
        if not url:
            raise ValueError("RSS item URL is required")

        scrape_result = await self.collect_url._scrape_url(url)
        # html_reader.main() reads html/url/title off task.input; the rest of the
        # Task is unused by the plain HTML-to-Markdown path.
        reader_task = Task(
            id="rss-item-parser",
            priority=0,
            namespace_id="",
            user_id="",
            function="collect",
            input={
                "url": scrape_result.final_url,
                "html": scrape_result.html,
                "title": scrape_result.title,
            },
        )
        result = await self.html_reader.main(reader_task, trace_info)
        return result.get("markdown", "")
