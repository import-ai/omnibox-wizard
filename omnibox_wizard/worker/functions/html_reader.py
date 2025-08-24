from urllib.parse import urlparse

from html2text import html2text
from opentelemetry import trace
from readability import Document

from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.worker.agent.html_title_extractor import HTMLTitleExtractor
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.functions.base_function import BaseFunction

tracer = trace.get_tracer(__name__)


class HTMLReaderV2(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.html_title_extractor = HTMLTitleExtractor(config.grimoire.openai.get_config("mini"))

    @tracer.start_as_current_span("HTMLReaderV2.run")
    async def run(self, task: Task, trace_info: TraceInfo, stream: bool = False) -> dict:
        input_dict = task.input
        html = input_dict["html"]
        url = input_dict["url"]

        domain: str = urlparse(url).netloc
        trace_info = trace_info.bind(domain=domain)

        result_dict: dict = await self.convert(html, trace_info)
        trace_info.info({k: v for k, v in result_dict.items() if k != "markdown"})
        return result_dict

    async def convert(self, html: str, trace_info: TraceInfo):
        span = trace.get_current_span()
        html_doc = Document(html)

        raw_title: str = html_doc.title()
        html_summary: str = html_doc.summary().strip()
        markdown: str = html2text(html_summary).strip()

        log_body: dict = {
            "len(html)": len(html),
            "len(html_summary)": len(html_summary),
            "compress_rate": f"{len(html_summary) * 100 / len(html): .2f}%",
            "len(markdown)": len(markdown),
        }
        trace_info.info(log_body)
        span.set_attributes(log_body)

        snippet: str = "\n".join(list(filter(bool, markdown.splitlines()))[:3])

        extraction = await self.html_title_extractor.ainvoke({"title": raw_title, "snippet": snippet}, trace_info)

        return {"title": extraction.title, "markdown": markdown}
