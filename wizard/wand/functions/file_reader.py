import mimetypes
import os
import tempfile

import httpx
from markitdown import MarkItDown

from common.trace_info import TraceInfo
from wizard.config import WorkerConfig
from wizard.entity import Task
from wizard.wand.functions.base_function import BaseFunction


class OfficeOperatorClient(httpx.AsyncClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def migrate(self, src_path: str, src_ext: str, dest_path: str):
        with open(src_path, "rb") as f:
            mimetype: str = mimetypes.guess_type(f"a{src_ext}")[0] or ""
            response: httpx.Response = await self.post(
                f"/api/v1/migrate/{src_ext.lstrip('.')}",
                files={"file": (src_path, f, mimetype)},
            )
        assert response.is_success, response.text
        with open(dest_path, "wb") as f:
            f.write(response.content)


class Convertor:
    def __init__(self, office_operator_base_url: str):
        self.markitdown: MarkItDown = MarkItDown()
        self.office_operator_base_url: str = office_operator_base_url

    async def convert(self, filepath: str, ext: str) -> str:
        if ext in [".pptx", ".docx", ".pdf", ".ppt", ".doc"]:
            path = filepath
            if ext in [".ppt", ".doc"]:
                path: str = filepath + "x"
                async with OfficeOperatorClient(base_url=self.office_operator_base_url) as client:
                    await client.migrate(filepath, ext, path)
            result = self.markitdown.convert(path)
            markdown: str = result.text_content
        elif ext in [".md", ".txt"]:
            with open(filepath, 'r') as f:
                markdown: str = f.read()
        else:
            raise ValueError(f"unsupported_type: {ext}")
        return markdown


class FileReader(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.base_url: str = config.backend.base_url

        self.mimetype_mapping: dict[str, str] = {
            "text/x-markdown": ".md"
        }
        self.convertor: Convertor = Convertor(config.task.office_operator_base_url)

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

            try:
                markdown: str = await self.convertor.convert(local_path, mime_ext)
            except ValueError:
                return {
                    "message": "unsupported_type",
                    "mime_ext": mime_ext,
                }

        result_dict: dict = {
            "title": title,
            "markdown": markdown
        }
        return result_dict
