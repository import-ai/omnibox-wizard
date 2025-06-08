import re

continuous_break_line_pattern = re.compile(r'\n+')


def remove_continuous_break_lines(text: str) -> str:
    return continuous_break_line_pattern.sub('\n', text).strip() if text else ''
