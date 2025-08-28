import base64
import os

import pytest

from omnibox_wizard.common import project_root
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.functions.file_readers.pdf_reader import PDFReader
from tests.omnibox_wizard.helper.fixture import remote_worker_config

input_base_dir: str = project_root.path("tests/omnibox_wizard/resources/files/pdfs")
output_base_dir: str = project_root.path("tests/omnibox_wizard/resources/files/ocr_output")


@pytest.mark.parametrize("filename", os.listdir(input_base_dir))
async def test_pdf_reader(remote_worker_config: WorkerConfig, filename: str):
    pdf_reader = PDFReader(base_url=remote_worker_config.task.pdf_reader_base_url)
    markdown, images = await pdf_reader.convert(os.path.join(input_base_dir, filename))
    output_dir: str = os.path.join(output_base_dir, filename.replace(".pdf", ""))
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
    with open(os.path.join(output_dir, "doc.md"), "w") as f:
        f.write(markdown)
    for img_name, img_data in images.items():
        img_path = os.path.join(output_dir, img_name)
        with open(img_path, "wb") as img_file:
            img_file.write(base64.b64decode(img_data))


@pytest.mark.parametrize("filename", os.listdir(input_base_dir))
async def test_get_pages(filename: str):
    pages = PDFReader.get_pages(os.path.join(input_base_dir, filename))
    for i, page in enumerate(pages):
        _ = page
