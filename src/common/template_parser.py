import re
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, Template

from src.common import project_root

continuous_bl: re.Pattern = re.compile(r"\n\n+")
template_dir = project_root.path("src/resources/prompt_templates")

env = Environment(loader=FileSystemLoader(template_dir))


def get_template(template_name: str) -> Template:
    return env.get_template(template_name)


def render_template(template: Template, now: str = None, **kwargs) -> str:
    now: str = now or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    render_result = template.render({**kwargs, "now": now})
    render_result = continuous_bl.sub("\n\n", render_result.strip())
    return render_result.strip()
