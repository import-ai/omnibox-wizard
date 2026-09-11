from opentelemetry import trace

from common.trace_info import TraceInfo
from common.utils import json_dumps
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.functions.base_function import BaseFunction
from wizard_common.worker.entity import Task
from omnibox_wizard.worker.agent.html_tags_extractor import (
    TagsExtractor,
    TagsExtractOutput,
)
from wizard_common.worker.omnibox_context import load_omnibox_markdown

tracer = trace.get_tracer(__name__)


class TagExtractor(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.tag_extractor = TagsExtractor(config.grimoire.openai)

    @tracer.start_as_current_span("TagExtractor.run")
    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        span = trace.get_current_span()
        input_dict = task.input
        title: str = input_dict.get("title", "")
        content: str = input_dict.get("content", "")
        lang: str | None = input_dict.get("lang", None)

        if not (content or title):
            raise ValueError("content or title is required for tag extraction")

        tag_rules = await load_omnibox_markdown(
            filename="TAGS.md",
            base_url=self.config.backend.base_url,
            namespace_id=task.namespace_id,
            user_id=task.user_id,
            resource_id=(task.payload or {}).get("resource_id"),
        )
        extract_input = {
            "title": title,
            "snippet": content.strip()[:512],
            "lang": lang,
        }
        if tag_rules:
            extract_input["tag_rules"] = tag_rules
        tags_extract_output: TagsExtractOutput = await self.tag_extractor.ainvoke(
            extract_input
        )
        span.set_attributes(
            {
                "extracted_tags": json_dumps(tags_extract_output.tags),
                "tags_count": len(tags_extract_output.tags),
            }
        )
        return tags_extract_output.model_dump(mode="json")
