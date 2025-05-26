import re

_pattern = re.compile(r"\{\{ (.*?) }}")


def render_template(template: str, mapping: dict) -> str:
    """
    Alternative of `str.format_map` using `{{ xxx }}` as placeholder instead.
    """
    return _pattern.sub(lambda m: mapping[m.group(1)], template)


__all__ = ["render_template"]
