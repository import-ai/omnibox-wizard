from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.wizard.grimoire.common_ai import CommonAI
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task
from omnibox_wizard.worker.functions.base_function import BaseFunction


class TitleGenerator(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.config = config
        self.common_ai = CommonAI(config.grimoire.openai)

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        input_dict = task.input
        text = input_dict.get("text", "")
        lang = input_dict.get("lang", None)

        if not text:
            raise ValueError("Text input is required for title generation")

        trace_info = trace_info.bind(text_length=len(text))
        trace_info.info({"message": "Starting title generation"})

        try:
            title = await self.common_ai.title(text, trace_info=trace_info, lang=lang)

            result_dict = {"title": title}
            trace_info.info({"generated_title": title, "message": "Title generation completed"})
            return result_dict

        except Exception as e:
            trace_info.error({"error": str(e), "message": "Failed to generate title"})
            raise
