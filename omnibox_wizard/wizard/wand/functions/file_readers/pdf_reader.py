import asyncio
import base64
import io
import re

import httpx
import shortuuid
from pydantic import BaseModel
from pypdf import PdfReader, PdfWriter

from omnibox_wizard.common.utils import remove_continuous_break_lines
from omnibox_wizard.wizard.entity import Image


class PageChunk(BaseModel):
    markdown: str
    is_start: bool
    is_end: bool
    images: list[Image]
    page_no: int
    index: int


class PDFReader:
    def __init__(self, base_url: str):
        self.base_url: str = base_url
        self.semaphore = asyncio.Semaphore(6)
        self.chinese_char_pattern = re.compile(r"[\u4e00-\u9fff]")

    @classmethod
    def get_pages(cls, filepath: str) -> list[str]:
        reader = PdfReader(filepath)
        for page in reader.pages:
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

    async def get_page_chunk(self, page_data: str, page_no: int) -> list[PageChunk]:
        payload = {"file": page_data, "fileType": 0, "visualize": False}
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

    async def _get_page_chunk(self, *args, **kwargs) -> list[PageChunk]:
        async with self.semaphore:
            return await self.get_page_chunk(*args, **kwargs)

    async def convert(self, pdf_path: str) -> tuple[str, list[Image]]:
        page_chunks = sum(await asyncio.gather(*[
            self._get_page_chunk(page_data, page_no)
            for page_no, page_data in enumerate(self.get_pages(pdf_path))
        ]), [])

        return self.concatenate_pages(page_chunks)
