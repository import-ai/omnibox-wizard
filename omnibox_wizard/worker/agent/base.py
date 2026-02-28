from common import project_root
from common.template_parser import TemplateParser
from wizard_common.agent.base import BaseAgent as _BaseAgent, InputType, OutputType


class BaseAgent(_BaseAgent[InputType, OutputType]):
    template_parser = TemplateParser(
        project_root.path("wizard_common/resources/prompt_templates")
    )
