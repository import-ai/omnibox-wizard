from omnibox.wizard.config import Config
from omnibox.wizard.grimoire.agent.agent import Agent


class Write(Agent):
    def __init__(self, config: Config):
        super().__init__(config=config, system_prompt_template_name="write.j2")
