from omnibox_wizard.common import project_root
from omnibox_wizard.common.template_parser import TemplateParser


def test_template_parser():
    template_parser = TemplateParser(base_dir=project_root.path("omnibox_wizard/resources/prompt_templates"))
    template = template_parser.get_template("ask.j2")
    rendered = template_parser.render_template(template, lang='简体中文', tools="")
    print(rendered)
