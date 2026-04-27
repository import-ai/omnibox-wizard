from common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.functions.base_function import BaseFunction
from wizard_common.worker.entity import Task
from worker.agent.html_tags_extractor import TagsExtractor, TagsExtractOutput


class TagExtractor(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.tag_extractor = TagsExtractor(
            config=config.grimoire.openai.get_config("mini")
        )

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        input_dict = task.input
        title: str = input_dict["title"]
        content: str = input_dict["content"]
        lang: str | None = input_dict.get("lang", None)

        if not content:
            raise ValueError("Text input is required for tag extraction")

        trace_info = trace_info.bind(text_length=len(content))
        trace_info.info({"message": "Starting tag extraction"})

        try:
            tags_extract_output: TagsExtractOutput = await self.tag_extractor.ainvoke(
                {
                    "title": title,
                    "snippet": content.strip()[:512],
                    "lang": lang,
                }
            )
            trace_info.info(
                {
                    "extracted_tags": tags_extract_output.tags,
                    "tags_count": len(tags_extract_output.tags),
                }
            )
            return tags_extract_output.model_dump(mode="json")

        except Exception as e:
            trace_info.error({"error": str(e), "message": "Failed to extract tags"})
            raise
