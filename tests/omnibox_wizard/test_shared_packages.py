from importlib.metadata import distribution
from importlib.resources import files
from pathlib import Path

from common import project_root
from omnibox_wizard.worker.agent.base import BaseAgent


def test_installed_shared_packages_and_application_templates():
    for name, module in [
        ("python-common", "common"),
        ("wizard-common", "wizard_common"),
    ]:
        installed = Path(distribution(name).locate_file(module)).resolve()
        assert Path(str(files(module))).resolve() == installed
    assert Path(project_root.path()).resolve() == Path(__file__).resolve().parents[2]
    assert (files("wizard_common") / "resources/prompt_templates/ask.j2").is_file()
    assert Path(BaseAgent.template_parser.base_dir).is_dir()
    assert BaseAgent.template_parser.get_template("tags_extract.j2") is not None
