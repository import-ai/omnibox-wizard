import io
import re

import httpcore
import httpx
import shortuuid

from omnibox_wizard.common.utils import remove_continuous_break_lines
from omnibox_wizard.worker.entity import Image
from omnibox_wizard.worker.functions.file_readers.utils import guess_extension


class OfficeReader(httpx.AsyncClient):
    """Unified Office Document Reader supporting both MarkItDown and Docling conversion engines."""
    base64_img_pattern: re.Pattern = re.compile(r"data:image/[^;]+;base64,([^\"')]+)")

    async def convert(self, file_path: str, ext: str, mimetype: str, retry_cnt: int = 3) -> tuple[str, list[Image]]:
        with open(file_path, "rb") as f:
            bytes_content: bytes = f.read()

        for i in range(retry_cnt):
            try:
                response: httpx.Response = await self.post(
                    "/v1/convert/file",
                    data={
                        "from_formats": [ext.lstrip('.')],
                        "to_formats": ["md"],
                        "image_export_mode": "embedded",
                    },
                    files={"files": (file_path, io.BytesIO(bytes_content), mimetype)},
                    timeout=7 * 24 * 3600,
                )
                assert response.is_success, response.text
                json_response: dict = response.json()
                markdown: str = json_response["document"]["md_content"]
                return self._extract_images_from_markdown(markdown)
            except (TimeoutError, httpcore.ReadTimeout, httpx.ReadTimeout):
                continue
        raise Exception("Failed to convert file after retries")

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