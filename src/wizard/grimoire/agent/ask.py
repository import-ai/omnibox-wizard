from src.wizard.config import OpenAIConfig, ToolsConfig, VectorConfig, Config
from src.wizard.grimoire.agent.agent import Agent


class Ask(Agent):
    def __init__(self, config: Config):
        super().__init__(config=config, system_prompt_template_name="ask.j2")
