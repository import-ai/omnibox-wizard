from src.common import project_root
from src.common.template_parser import TemplateParser


def test_template_parser():
    template_parser = TemplateParser(base_dir=project_root.path("src/resources/prompt_templates"))
    template = template_parser.get_template("ask.j2")
    rendered = template_parser.render_template(template, lang='简体中文', tools="")
    print(rendered)
