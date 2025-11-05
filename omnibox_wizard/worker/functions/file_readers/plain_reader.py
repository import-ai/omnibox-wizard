import chardet


def read_text_file(filepath: str) -> str:
    """
    Read a text file with automatic encoding detection.

    Args:
        filepath: Path to the text file

    Returns:
        The decoded text content

    Raises:
        UnicodeDecodeError: If the file cannot be decoded with the detected encoding
    """
    with open(filepath, 'rb') as f:
        raw_data = f.read()

    detected = chardet.detect(raw_data)
    encoding = detected['encoding'] or 'utf-8'

    return raw_data.decode(encoding)
