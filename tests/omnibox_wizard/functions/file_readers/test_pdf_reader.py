import base64
import os

import pytest

from omnibox_wizard.common import project_root
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.functions.file_readers.pdf_reader import PDFReader, FileType
from tests.omnibox_wizard.helper.fixture import remote_worker_config

input_base_dir: str = project_root.path("tests/omnibox_wizard/resources/files/pdfs")
output_base_dir: str = project_root.path("tests/omnibox_wizard/resources/files/ocr_output")
os.makedirs(output_base_dir, exist_ok=True)

filenames = [filename for filename in os.listdir(input_base_dir) if filename.endswith(".pdf")]

@pytest.mark.parametrize("filename", filenames)
async def test_pdf_reader(remote_worker_config: WorkerConfig, filename: str):
    if '巴曙松' not in filename:
        pytest.skip()
    pdf_reader = PDFReader(base_url=remote_worker_config.task.pdf_reader_base_url)
    markdown, images = await pdf_reader.convert(os.path.join(input_base_dir, filename), page_type=FileType.IMAGE)
    output_dir: str = os.path.join(output_base_dir, filename.replace(".pdf", ""))
    os.makedirs(output_dir, exist_ok=True)
    with open(os.path.join(output_dir, "doc.md"), "w") as f:
        f.write(markdown)
    for image in images:
        img_path = os.path.join(output_dir, image.link)
        with open(img_path, "wb") as img_file:
            img_file.write(base64.b64decode(image.data))


@pytest.mark.parametrize("filename", filenames)
@pytest.mark.parametrize("file_type", [FileType.PDF, FileType.IMAGE])
async def test_get_pages(filename: str, file_type: int):
    pages = PDFReader.get_pages(os.path.join(input_base_dir, filename), page_type=file_type)
    basedir = os.path.join(output_base_dir, filename.replace(".pdf", ""))
    os.makedirs(basedir, exist_ok=True)
    for i, page in enumerate(pages):
        with open(os.path.join(basedir, f"page_{i}.{'jpg' if file_type == FileType.IMAGE else 'pdf'}"), "wb") as f:
            f.write(base64.b64decode(page))
