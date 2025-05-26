import json as jsonlib
import re

_json_markdown_re = re.compile(r"```json(.*)", re.DOTALL)
_json_strip_chars = " \n\r\t`"


def parse_json(text: str) -> dict | list:
    if (match := _json_markdown_re.search(text)) is not None:
        json_string: str = match.group(1)
        json_string: str = json_string.strip(_json_strip_chars)
        return jsonlib.loads(json_string)
    return jsonlib.loads(text)


__all__ = ["parse_json"]
