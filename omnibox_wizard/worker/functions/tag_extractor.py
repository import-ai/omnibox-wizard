from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.wizard.grimoire.common_ai import CommonAI
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.functions.base_function import BaseFunction


class TagExtractor(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.common_ai = CommonAI(config.grimoire.openai)

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        input_dict = task.input
        text = input_dict.get("text", "")
        lang = input_dict.get("lang", None)

        if not text:
            raise ValueError("Text input is required for tag extraction")

        trace_info = trace_info.bind(text_length=len(text))
        trace_info.info({"message": "Starting tag extraction"})

        try:
            tags = await self.common_ai.tags(text, trace_info=trace_info, lang=lang)

            result_dict = {"tags": tags}
            trace_info.info({"extracted_tags": tags, "tags_count": len(tags)})
            return result_dict

        except Exception as e:
            trace_info.error({"error": str(e), "message": "Failed to extract tags"})
            raise
