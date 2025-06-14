from src.wizard.config import OpenAIConfig, ToolsConfig, VectorConfig
from src.wizard.grimoire.agent.agent import Agent


class Write(Agent):
    def __init__(
            self,
            openai_config: OpenAIConfig,
            tools_config: ToolsConfig,
            vector_config: VectorConfig,
            reranker_config: OpenAIConfig | None = None,
    ):
        super().__init__(
            openai_config=openai_config,
            tools_config=tools_config,
            vector_config=vector_config,
            system_prompt_template_name="write.j2",
            reranker_config=reranker_config,
        )
