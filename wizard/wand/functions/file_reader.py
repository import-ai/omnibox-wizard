import mimetypes
import os
import tempfile

import httpx
from markitdown import MarkItDown

from common.trace_info import TraceInfo
from wizard.config import BackendConfig
from wizard.entity import Task
from wizard.wand.functions.base_function import BaseFunction


class FileReader(BaseFunction):
    def __init__(self, config: BackendConfig):
        self.markitdown: MarkItDown = MarkItDown()
        self.base_url: str = config.base_url

        self.mimetype_mapping: dict[str, str] = {
            "text/x-markdown": ".md"
        }

    async def download(self, resource_id: str, target: str):
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            async with client.stream('GET', f'/internal/api/v1/resources/files/{resource_id}') as response:
                response.raise_for_status()
                with open(target, 'wb') as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)

    def guess_extension(self, mimetype: str) -> str | None:
        if mime_ext := mimetypes.guess_extension(mimetype):
            return mime_ext
        if mime_ext := self.mimetype_mapping.get(mimetype, None):
            return mime_ext
        if mimetype.startswith("text/"):
            return ".txt"
        return None

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        task_input: dict = task.input

        title: str = task_input['title']
        filename: str = task_input.get('filename', task_input['original_name'])
        resource_id: str = task_input['resource_id']
        mimetype: str = task_input['mimetype']

        with tempfile.TemporaryDirectory() as temp_dir:
            local_path: str = os.path.join(temp_dir, filename)
            await self.download(resource_id, local_path)

            mime_ext: str | None = self.guess_extension(mimetype)

            if mime_ext in [".pptx", ".docx", ".pdf"]:
                result = self.markitdown.convert(local_path)
                markdown: str = result.text_content
            elif mime_ext in [".md", ".txt"]:
                with open(local_path, 'r') as f:
                    markdown: str = f.read()
            else:
                return {
                    "message": "unsupported_type",
                    "mime_ext": mime_ext
                }

        result_dict: dict = {
            "title": title,
            "markdown": markdown
        }
        return result_dict
