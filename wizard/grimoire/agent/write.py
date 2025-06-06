from wizard.config import OpenAIConfig, ToolsConfig, VectorConfig
from wizard.grimoire.agent.agent import Agent


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
            system_prompt_template_path="resources/prompts/write.md",
            reranker_config=reranker_config,
        )
