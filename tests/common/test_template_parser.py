from src.common.template_parser import get_template, render_template


def test_template_parser():
    template = get_template("ask.j2")
    rendered = render_template(template, lang='简体中文', tools="")
    print(rendered)
