import io
import re
import base64
from pathlib import Path
from typing import Optional
from enum import Enum

import httpcore
import httpx
import shortuuid
from markitdown import MarkItDown
from docling.document_converter import DocumentConverter
from docling.datamodel.base_models import ConversionStatus
from docling_core.types.doc.base import ImageRefMode
from omnibox_wizard.common.utils import remove_continuous_break_lines
from omnibox_wizard.worker.entity import Image
from omnibox_wizard.worker.functions.file_readers.utils import guess_extension


class ConversionEngine(Enum):
    MARKITDOWN = "markitdown"
    DOCLING = "docling"


class OfficeReader:
    """Unified Office Document Reader supporting both MarkItDown and Docling conversion engines."""
    
    def __init__(self, engine: ConversionEngine = ConversionEngine.DOCLING):
        self.engine = engine
        self.base64_img_pattern: re.Pattern = re.compile(r"data:image/[^;]+;base64,([^\"')]+)")
        
        if engine == ConversionEngine.MARKITDOWN:
            self.markitdown: MarkItDown = MarkItDown()
        elif engine == ConversionEngine.DOCLING:
            self.converter = DocumentConverter()

    def convert(self, file_path: str) -> tuple[str, list[Image]]:
        """
        Convert Office document to Markdown format and extract images.

        Args:
            file_path: The path to the Office document file.
            
        Returns:
            tuple[str, list[Image]]: A tuple containing the converted Markdown content and a list of extracted images.
        """
        if self.engine == ConversionEngine.MARKITDOWN:
            return self._convert_with_markitdown(file_path)
        elif self.engine == ConversionEngine.DOCLING:
            return self._convert_with_docling(file_path)
        else:
            raise ValueError(f"Unsupported conversion engine: {self.engine}")
    
    def _convert_with_markitdown(self, file_path: str) -> tuple[str, list[Image]]:
        result = self.markitdown.convert(file_path, keep_data_uris=True)
        markdown: str = result.text_content
        return self._extract_images_from_markdown(markdown)
    
    def _convert_with_docling(self, file_path: str) -> tuple[str, list[Image]]:
        source = Path(file_path)
        result = self.converter.convert(source)
        markdown = result.document.export_to_markdown(image_mode=ImageRefMode.EMBEDDED)
        return self._extract_images_from_markdown(markdown)
    
    def _extract_images_from_markdown(self, markdown: str) -> tuple[str, list[Image]]:
        images: list[Image] = []
        for match in self.base64_img_pattern.finditer(markdown):
            base64_data: str = match.group(1)
            mimetype = match.group(0).split(';')[0].split(':')[1]
            ext: str = guess_extension(mimetype) or ("." + mimetype.split('/')[1])
            uuid: str = shortuuid.uuid()
            link: str = f"{uuid}{ext}"
            images.append(Image(data=base64_data, mimetype=mimetype, link=link, name=link))
            markdown = markdown.replace(match.group(0), link)
        return remove_continuous_break_lines(markdown), images

class OfficeOperatorClient(httpx.AsyncClient):

    async def migrate(self, src_path: str, src_ext: str, dest_path: str, mimetype: str, retry_cnt: int = 3):
        with open(src_path, "rb") as f:
            bytes_content: bytes = f.read()

        for i in range(retry_cnt):
            try:
                response: httpx.Response = await self.post(
                    f"/api/v1/migrate/{src_ext.lstrip('.')}",
                    files={"file": (src_path, io.BytesIO(bytes_content), mimetype)},
                )
                assert response.is_success, response.text
                with open(dest_path, "wb") as f:
                    f.write(response.content)
            except (TimeoutError, httpcore.ReadTimeout, httpx.ReadTimeout):
                continue
            break