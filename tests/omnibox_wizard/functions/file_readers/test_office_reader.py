import mimetypes
import os

import pytest
from dotenv import load_dotenv

from omnibox_wizard.common import project_root
from omnibox_wizard.worker.functions.file_readers.office_reader import OfficeReader

load_dotenv()


@pytest.fixture(scope="session")
def office_reader() -> OfficeReader:
    return OfficeReader(base_url=os.environ["OBW_TASK_DOCLING_BASE_URL"])


@pytest.mark.parametrize("filename", [
    "test.docx",
])
async def test_convertor(office_reader: OfficeReader, filename):
    filepath: str = project_root.path(os.path.join("tests/omnibox_wizard/resources/files", filename))
    mimetype: str = mimetypes.guess_type(filepath)[0] or "application/octet-stream"
    markdown, images = await office_reader.convert(filepath, "." + filename.split(".")[-1], mimetype)
    print(markdown)
    output_dir: str = os.path.join(
        project_root.path("tests/omnibox_wizard/resources/files/office_reader_output"),
        filename.replace(".docx", "")
    )
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    with open(os.path.join(output_dir, "doc.md"), "w") as f:
        f.write(markdown)
    for image in images:
        img_path = os.path.join(output_dir, image.link)
        with open(img_path, "wb") as f:
            image.dump(f)
