from datetime import datetime
from typing import List, AsyncIterator

from openai import AsyncOpenAI

from common import project_root
from wizard.config import OpenAIConfig
from wizard.grimoire.entity.retrieval import BaseRetrieval


class RAG:

    def __init__(self, openai_config: OpenAIConfig):
        self.client = AsyncOpenAI(api_key=openai_config.api_key, base_url=openai_config.base_url)
        self.model = openai_config.model
        with project_root.open("resources/prompts/rag.md") as f:
            self.prompt: str = f.read()

    @classmethod
    def build_context(cls, retrieval_list: List[BaseRetrieval]) -> str:
        retrieval_prompt_list: List[str] = []
        for i, retrieval in enumerate(retrieval_list):
            prompt_list: List[str] = [
                f"<cite:{i + 1}>",
                retrieval.to_prompt()
            ]
            retrieval_prompt_list.append("\n".join(prompt_list))
        return "\n\n".join(retrieval_prompt_list)

    def messages_prepare(self, query: str, template: str, retrieval_list: List[BaseRetrieval]) -> List[dict]:
        context = self.build_context(retrieval_list)
        messages = [
            {"role": "system", "content": template.format_map({
                "now": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "context": context,
                "lang": "简体中文"
            })},
            {"role": "user", "content": query}
        ]
        return messages

    async def astream(self, query: str, retrieval_list: List[BaseRetrieval]) -> AsyncIterator[str]:
        messages = self.messages_prepare(query, self.prompt, retrieval_list)
        async for chunk in await self.client.chat.completions.create(model=self.model, messages=messages, stream=True):
            if delta := chunk.choices[0].delta.content:
                yield delta
