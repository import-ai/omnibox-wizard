import mimetypes

mimetype_mapping: dict[str, str] = {
    "text/x-markdown": ".md"
}


def guess_extension(mimetype: str) -> str | None:
    if mime_ext := mimetypes.guess_extension(mimetype):
        return mime_ext
    if mime_ext := mimetype_mapping.get(mimetype, None):
        return mime_ext
    if mimetype.startswith("text/"):
        return ".txt"
    return None
