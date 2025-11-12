import os
import tempfile

import httpx
from httpx import AsyncHTTPTransport

from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task, Image
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.worker.functions.file_readers.md_reader import MDReader
from omnibox_wizard.worker.functions.file_readers.office_reader import OfficeReader, OfficeOperatorClient
from omnibox_wizard.worker.functions.file_readers.plain_reader import read_text_file
from omnibox_wizard.worker.functions.file_readers.utils import guess_extension


class Convertor:
    def __init__(
            self,
            docling_base_url: str | None = None,
            office_operator_base_url: str | None = None,
    ):
        self.office_reader: OfficeReader | None = OfficeReader(base_url=docling_base_url) if docling_base_url else None
        self.office_operator_base_url: str | None = office_operator_base_url
        self.md_reader: MDReader = MDReader()

        self.supported_extensions = ['.md', '.txt']
        if self.office_reader:
            self.supported_extensions.extend(['.pptx', '.docx'])
            if self.office_operator_base_url:
                self.supported_extensions.extend([".ppt", '.doc'])

    async def convert(self, filepath: str, mime_ext: str, mimetype: str, trace_info: TraceInfo, **kwargs) -> tuple[
        str, list[Image], dict]:
        if mime_ext in [".pptx", ".docx", ".ppt", ".doc"] and self.office_reader:
            path = filepath
            ext = mime_ext
            if mime_ext in [".ppt", ".doc"]:
                if not self.office_operator_base_url:
                    raise ValueError(f"unsupported_type: {mime_ext}")
                path: str = filepath + "x"
                ext = mime_ext + "x"
                async with OfficeOperatorClient(base_url=self.office_operator_base_url) as client:
                    await client.migrate(filepath, mime_ext, path, mimetype)
            markdown, images = await self.office_reader.convert(path, ext, mimetype)
            return markdown, images, {}
        elif mime_ext == ".md":
            return self.md_reader.convert(filepath)
        elif mime_ext == ".plain":
            markdown: str = read_text_file(filepath)
        else:
            raise ValueError(f"unsupported_type: {mime_ext}")
        return markdown, [], {}


class FileReader(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.base_url: str = config.backend.base_url

        self.convertor: Convertor = Convertor(
            office_operator_base_url=config.task.office_operator_base_url,
            docling_base_url=config.task.docling_base_url,
        )
        self.supported_extensions = self.convertor.supported_extensions

    async def get_file_info(self, namespace_id: str, resource_id: str):
        try:
            async with httpx.AsyncClient(base_url=self.base_url, transport=AsyncHTTPTransport(retries=3)) as client:
                response = await client.get(f'/internal/api/v1/namespaces/{namespace_id}/resources/{resource_id}/file')
                response.raise_for_status()
                file_info = response.json()
                return file_info
        except httpx.HTTPStatusError:
            return None

    async def download(self, namespace_id: str, resource_id: str, target: str):
        file_info = await self.get_file_info(namespace_id, resource_id)
        if not file_info:
            await self.download_old(resource_id, target)
            return

        async with httpx.AsyncClient() as client:
            async with client.stream('GET', file_info['public_url']) as response:
                response.raise_for_status()
                with open(target, 'wb') as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)

    async def download_old(self, resource_id: str, target: str):
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            async with client.stream('GET', f'/internal/api/v1/resources/files/{resource_id}') as response:
                response.raise_for_status()
                with open(target, 'wb') as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        task_input: dict = task.input

        title: str = task_input['title']
        filename: str = task_input.get('filename', task_input['original_name'])
        resource_id: str = task_input['resource_id']
        mimetype: str = task_input['mimetype']

        # Extract additional parameters for video processing
        language: str = task_input.get('language', 'zh')
        style: str = task_input.get('style', 'Concise Style')
        include_screenshots: bool = task_input.get('include_screenshots', True)
        include_links: bool = task_input.get('include_links', False)

        with tempfile.TemporaryDirectory() as temp_dir:
            local_path: str = os.path.join(temp_dir, filename)
            await self.download(task.namespace_id, resource_id, local_path)

            mime_ext: str | None = guess_extension(mimetype)

            try:
                # Pass additional parameters for video processing
                convert_params = {
                    'language': language,
                    'style': style,
                    'include_screenshots': include_screenshots,
                    'include_links': include_links
                }
                markdown, images, metadata = await self.convertor.convert(
                    local_path, mime_ext, mimetype, trace_info, **convert_params)
            except ValueError:
                return {
                    "message": "unsupported_type",
                    "mime_ext": mime_ext,
                    "mimetype": mimetype,
                }

        result_dict: dict = {"title": (metadata or {}).pop("title", None) or title, "markdown": markdown}
        if images:
            result_dict['images'] = [image.model_dump(exclude_none=True) for image in images]
        if metadata:
            result_dict['metadata'] = metadata
        return result_dict
