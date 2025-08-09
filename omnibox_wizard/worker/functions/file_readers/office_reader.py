import io
import re

import httpcore
import httpx
import shortuuid
from markitdown import MarkItDown

from omnibox_wizard.common.utils import remove_continuous_break_lines
from omnibox_wizard.worker.entity import Image
from omnibox_wizard.worker.functions.file_readers.utils import guess_extension


class OfficeReader:
    def __init__(self):
        self.markitdown: MarkItDown = MarkItDown()
        self.base64_img_pattern: re.Pattern = re.compile(r"data:image/[^;]+;base64,([^\"')]+)")

    def convert(self, file_path: str) -> tuple[str, list[Image]]:
        result = self.markitdown.convert(file_path, keep_data_uris=True)
        markdown: str = result.text_content
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
