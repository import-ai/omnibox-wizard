import json

from common import project_root
from common.config_loader import Loader
from wizard.config import Config, ENV_PREFIX
from wizard.entity import Task
from wizard.wand.functions.html_to_markdown import HTMLToMarkdown
from dotenv import load_dotenv


async def test_content_extract():
    load_dotenv()
    loader = Loader(Config, ENV_PREFIX)
    config = loader.load(config_dict={
        "vector": {"host": "foo"},
        "db": {"url": "bar"}
    })

    with project_root.open("tests/resources/input.json") as f:
        input_dict = json.load(f)

    task = Task(namespace_id="foo", user_id="bar", function="collect", input=input_dict)
    worker = HTMLToMarkdown(config=config)
    result = await worker.run(task)
    print(result)
