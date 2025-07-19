from urllib.parse import urlparse

from html2text import html2text
from readability import Document

from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.functions.base_function import BaseFunction


class HTMLReaderV2(BaseFunction):
    async def run(self, task: Task, trace_info: TraceInfo, stream: bool = False) -> dict:
        input_dict = task.input
        html = input_dict["html"]
        url = input_dict["url"]

        domain: str = urlparse(url).netloc
        trace_info = trace_info.bind(domain=domain)

        html_doc = Document(html)

        title = html_doc.title()
        html_summary = html_doc.summary().strip()
        markdown: str = html2text(html_summary).strip()

        trace_info.info({
            "len(html)": len(html),
            "len(html_summary)": len(html_summary),
            "compress_rate": f"{len(html_summary) * 100 / len(html): .2f}%",
            "len(markdown)": len(markdown),
        })

        result_dict: dict = {"title": title, "markdown": markdown}
        trace_info.info({k: v for k, v in result_dict.items() if k != "markdown"})
        return result_dict
