import os

import pytest

from omnibox_wizard.common import project_root
from omnibox_wizard.worker.functions.file_readers.office_reader import OfficeReader


@pytest.fixture(scope="session")
def office_reader() -> OfficeReader:
    return OfficeReader()


@pytest.mark.parametrize("filename", [
    "test.docx",
])
async def test_convertor(office_reader: OfficeReader, filename):
    filepath: str = project_root.path(os.path.join("tests/omnibox_wizard/resources/files", filename))
    markdown, images = office_reader.convert(filepath)
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
