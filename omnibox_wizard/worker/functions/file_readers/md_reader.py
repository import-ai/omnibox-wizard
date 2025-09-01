import frontmatter

from omnibox_wizard.worker.entity import Image


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
        with open(file_path, 'r', encoding='utf-8') as f:
            post = frontmatter.load(f)

        markdown_content = post.content
        metadata = dict(post.metadata)

        return markdown_content, [], exclude_empty(exclude_none(metadata))
