import re

continuous_break_line_pattern = re.compile(r'\n\n+')


def remove_continuous_break_lines(text: str) -> str:
    return continuous_break_line_pattern.sub('\n\n', text).strip() if text else ''
