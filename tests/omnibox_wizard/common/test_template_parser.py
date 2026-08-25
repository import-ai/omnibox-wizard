from common import project_root
from common.template_parser import TemplateParser


def render_ask_prompt() -> str:
    template_parser = TemplateParser(
        base_dir=project_root.path("wizard_common/resources/prompt_templates")
    )
    template = template_parser.get_template("ask.j2")
    return template_parser.render_template(template, lang="简体中文", tools="")


def test_template_parser():
    rendered = render_ask_prompt()
    print(rendered)
    assert "# Role Setting" in rendered
    assert "# Task Description" in rendered
    assert "# Guidelines" in rendered


def test_ask_prompt_declares_capability_boundary():
    rendered = render_ask_prompt()
    assert "# Capability Boundaries" in rendered
    assert "Agent 1.1" in rendered
    assert "Agent 2.1" in rendered
    # The two search tools, and nothing beyond them.
    assert "read-only" in rendered
    # The upgrade invitation must be capped at a single mention per reply.
    assert "exactly once in the entire reply" in rendered
    # The boundary section must stay ahead of the general guidelines.
    assert rendered.index("# Capability Boundaries") < rendered.index("# Guidelines")
