import frontmatter

from omnibox_wizard.worker.entity import Image
from omnibox_wizard.worker.functions.file_readers.plain_reader import read_text_file


def exclude_none(d: dict) -> dict:
    return {k: v for k, v in d.items() if v is not None}


def is_empty(v) -> bool:
    if v is None:
        return True
    if isinstance(v, (str, list, dict)) and len(v) == 0:
        return True
    return False


def exclude_empty(d: dict) -> dict:
    return {k: v for k, v in d.items() if not is_empty(v)}


class MDReader:
    @classmethod
    def convert(cls, file_path: str) -> tuple[str, list[Image], dict]:
        content = read_text_file(file_path)
        post = frontmatter.loads(content)

        markdown_content = post.content
        metadata = dict(post.metadata)

        return markdown_content, [], exclude_empty(exclude_none(metadata))
