import mimetypes

mimetype_mapping: dict[str, str] = {
    "text/x-markdown": ".md",
    "audio/vnd.wave": ".wav",
    "audio/x-m4a": ".m4a",
}


def guess_extension(mimetype: str) -> str | None:
    if mime_ext := mimetype_mapping.get(mimetype, None):
        return mime_ext
    if mime_ext := mimetypes.guess_extension(mimetype):
        return mime_ext
    return None


def guess_mimetype(filename: str) -> str:
    mimetype: str = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return mimetype
