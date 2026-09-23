from pathlib import Path

import httpx
import pytest

from omnibox_wizard.worker.functions import file_reader
from omnibox_wizard.worker.functions.file_reader import Convertor


@pytest.mark.parametrize(
    "extension,target",
    [(ext, "docx") for ext in ("doc", "wps", "wpt", "rtf", "odt")]
    + [(ext, "pptx") for ext in ("ppt", "dps", "dpt", "odp")],
)
async def test_office_conversion_routes_and_output_suffix(
    extension, target, tmp_path, monkeypatch
):
    requests = []

    def handle(request):
        requests.append(request)
        if request.url.host == "office":
            assert request.url.path == f"/api/v1/migrate/{extension}"
            return httpx.Response(200, content=b"converted document")
        assert request.url.host == "docling"
        assert request.url.path == "/v1/convert/file"
        assert f"test.{target}".encode() in request.content
        assert b"converted document" in request.content
        return httpx.Response(
            200, json={"document": {"md_content": "# Parsed content"}}
        )

    monkeypatch.setattr(
        file_reader, "AsyncHTTPTransport", lambda **kwargs: httpx.MockTransport(handle)
    )
    path = tmp_path / f"test.{extension.upper()}"
    path.write_bytes(b"source document")
    converter = Convertor(32768, "http://docling", "http://office")
    assert "." + extension in converter.supported_extensions
    markdown, images, metadata = await converter.convert(str(path))
    assert markdown == "# Parsed content"
    assert images == []
    assert metadata == {}
    assert len(requests) == 2
    assert Path(path).with_suffix("." + target).read_bytes() == b"converted document"


def test_office_formats_require_both_services():
    for docling, office in [
        (None, None),
        ("http://docling", None),
        (None, "http://office"),
    ]:
        supported = Convertor.get_supported_extensions(docling, office)
        assert not set([".wps", ".wpt", ".rtf", ".odt", ".dps", ".dpt", ".odp"]) & set(
            supported
        )
    assert ".xls" not in Convertor.get_supported_extensions(
        "http://docling", "http://office"
    )
