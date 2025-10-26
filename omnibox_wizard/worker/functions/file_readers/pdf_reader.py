import base64
import io
import re
from typing import Any, Generator

import httpx
import pymupdf
import shortuuid
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter

from omnibox_wizard.common.utils import remove_continuous_break_lines
from omnibox_wizard.worker.entity import Image


class PageChunk(BaseModel):
    markdown: str
    is_start: bool
    is_end: bool
    images: list[Image]
    page_no: int
    index: int


class FileType:
    PDF = 0
    IMAGE = 1


class PDFReader:
    def __init__(self, base_url: str):
        self.base_url: str = base_url
        self.chinese_char_pattern = re.compile(r"[\u4e00-\u9fff]")

    @classmethod
    def pdf_reader(cls, filepath: str) -> io.BytesIO:
        # Handle PDFs that may have wrapper data before the actual PDF content
        with open(filepath, 'rb') as f:
            data = f.read()

        # Find the PDF header position
        pdf_start = data.find(b'%PDF')
        if pdf_start == -1:
            raise ValueError(f"No PDF header found in {filepath}")

        # Extract the actual PDF data
        pdf_data = data[pdf_start:]

        return io.BytesIO(pdf_data)

    @classmethod
    def get_pages(cls, filepath: str, page_type: int = FileType.PDF) -> Generator[str, Any, None]:
        bytes_pdf = cls.pdf_reader(filepath)
        if page_type == FileType.IMAGE:
            pdf_document = pymupdf.open(stream=bytes_pdf, filetype='pdf')
            for i in range(len(pdf_document)):
                page = pdf_document[i]
                mat = pymupdf.Matrix(2.0, 2.0)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("jpeg")
                yield base64.b64encode(img_bytes).decode("ascii")
        else:
            pdf_reader = PdfReader(cls.pdf_reader(filepath))
            for page in pdf_reader.pages:
                writer = PdfWriter()
                writer.add_page(page)

                with io.BytesIO() as output_stream:
                    writer.write(output_stream)
                    page_bytes: bytes = output_stream.getvalue()
                yield base64.b64encode(page_bytes).decode("ascii")

    def concatenate_pages(self, page_chunks: list[PageChunk]) -> tuple[str, list[Image]]:
        markdown: str = ""
        images: list[Image] = []

        previous_is_end = True

        for page_chunk in page_chunks:
            images.extend(page_chunk.images)

            # Determine whether to add a space or a newline
            if not page_chunk.is_start and not previous_is_end:
                last_char_of_markdown = markdown[-1] if markdown else ""
                first_char_of_handler = page_chunk.markdown[0] if page_chunk.markdown else ""

                # Check if the last character and the first character are Chinese characters
                last_is_chinese_char = (
                    self.chinese_char_pattern.match(last_char_of_markdown)
                    if last_char_of_markdown
                    else False
                )
                first_is_chinese_char = (
                    self.chinese_char_pattern.match(first_char_of_handler)
                    if first_char_of_handler
                    else False
                )
                if not (last_is_chinese_char or first_is_chinese_char):
                    markdown += " " + page_chunk.markdown
                else:
                    markdown += page_chunk.markdown
            else:
                markdown += "\n\n" + page_chunk.markdown
            previous_is_end = page_chunk.is_end

        return remove_continuous_break_lines(markdown), images

    async def get_page_chunk(self, page_data: str, page_no: int, page_type: int = FileType.PDF) -> list[PageChunk]:
        payload = {"file": page_data, "fileType": page_type, "visualize": False}
        page_chunks: list[PageChunk] = []
        async with httpx.AsyncClient(base_url=self.base_url, timeout=300) as client:
            response = await client.post("/layout-parsing", json=payload)
            assert response.is_success, response.text
            json_response: dict = response.json()

        for i, res in enumerate(json_response["result"]["layoutParsingResults"]):
            markdown: str = res["markdown"]["text"]
            images: list[dict[str, str]] = [
                {
                    "name": k,
                    "link": shortuuid.uuid() + "." + k.split(".")[-1],
                    "data": v,
                    "mimetype": "image/jpeg"
                }
                for k, v in res["markdown"]["images"].items()
            ]
            for image in images:
                markdown = markdown.replace(image["name"], image["link"])

            page_chunks.append(PageChunk.model_validate({
                "markdown": markdown,
                "images": images,
                "page_no": page_no,
                "index": i,
                "is_start": res["markdown"]["isStart"],
                "is_end": res["markdown"]["isEnd"],
            }))
        return page_chunks

    async def convert(self, pdf_path: str, page_type: int = FileType.PDF) -> tuple[str, list[Image]]:
        page_chunks: list[PageChunk] = []
        for page_no, page_data in enumerate(self.get_pages(pdf_path, page_type=page_type)):
            page_chunk = await self.get_page_chunk(page_data, page_no, page_type=page_type)
            page_chunks.extend(page_chunk)
        return self.concatenate_pages(page_chunks)
