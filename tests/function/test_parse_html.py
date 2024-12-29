from common import project_root
from wizard.wand.functions.html_to_markdown import HTMLToMarkdown


async def test_parse_html():
    c = HTMLToMarkdown()
    with project_root.open("a") as f:
        content = f.read().strip("'")
    result = await c.run({"html": content, "url": "foo"})
    print(result["markdown"])
