import os
import tempfile

import httpx

from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.wizard.config import OpenAIConfig
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task, Image
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.worker.functions.file_readers.audio_reader import ASRClient, M4AConvertor
from omnibox_wizard.worker.functions.file_readers.md_reader import MDReader
from omnibox_wizard.worker.functions.file_readers.office_reader import OfficeReader, OfficeOperatorClient
from omnibox_wizard.worker.functions.file_readers.pdf_reader import PDFReader, FileType
from omnibox_wizard.worker.functions.file_readers.plain_reader import read_text_file
from omnibox_wizard.worker.functions.file_readers.utils import guess_extension
from omnibox_wizard.worker.functions.file_readers.video_reader import VideoReader


class Convertor:
    def __init__(
            self,
            office_operator_base_url: str,
            asr_config: OpenAIConfig,
            pdf_reader_base_url: str,
            docling_base_url: str,
            worker_config: WorkerConfig,
    ):
        self.office_reader: OfficeReader = OfficeReader(base_url=docling_base_url)
        self.office_operator_base_url: str = office_operator_base_url
        self.asr_client: ASRClient = ASRClient(
            model=asr_config.model,
            base_url=asr_config.base_url,
            headers={"Authorization": f"Bearer {asr_config.api_key}"},
        )
        self.pdf_reader: PDFReader = PDFReader(base_url=pdf_reader_base_url)
        self.m4a_convertor: M4AConvertor = M4AConvertor()
        self.video_reader: VideoReader = VideoReader(worker_config)
        self.md_reader: MDReader = MDReader()

    async def convert(self, filepath: str, mime_ext: str, mimetype: str, trace_info: TraceInfo, **kwargs) -> tuple[
        str, list[Image], dict]:
        if mime_ext in [".pptx", ".docx", ".ppt", ".doc"]:
            path = filepath
            ext = mime_ext
            if mime_ext in [".ppt", ".doc"]:
                path: str = filepath + "x"
                ext = mime_ext + "x"
                async with OfficeOperatorClient(base_url=self.office_operator_base_url) as client:
                    await client.migrate(filepath, mime_ext, path, mimetype)
            markdown, images = await self.office_reader.convert(path, ext, mimetype)
            return markdown, images, {}
        elif mime_ext in [".pdf"]:
            markdown, images = await self.pdf_reader.convert(filepath, page_type=FileType.IMAGE)
            return markdown, images, {}
        elif mime_ext == ".md":
            return self.md_reader.convert(filepath)
        elif mime_ext == ".plain":
            markdown: str = read_text_file(filepath)
        elif mime_ext in [".wav", ".mp3", ".pcm", ".opus", ".webm", ".m4a"]:
            if mime_ext == ".m4a":
                filepath = self.m4a_convertor.convert(filepath)
            markdown: str = await self.asr_client.transcribe(filepath, mimetype)
        elif mime_ext in [".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm"]:
            return await self.video_reader.convert(filepath, trace_info, **kwargs)
        else:
            raise ValueError(f"unsupported_type: {mime_ext}")
        return markdown, [], {}


class FileReader(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.base_url: str = config.backend.base_url

        self.convertor: Convertor = Convertor(
            office_operator_base_url=config.task.office_operator_base_url,
            asr_config=config.task.asr,
            pdf_reader_base_url=config.task.pdf_reader_base_url,
            docling_base_url=config.task.docling_base_url,
            worker_config=config,
        )

    async def get_file_info(self, namespace_id: str, resource_id: str):
        try:
            async with httpx.AsyncClient(base_url=self.base_url) as client:
                response = await client.get(f'/internal/api/v1/namespaces/{namespace_id}/resources/{resource_id}/file')
                response.raise_for_status()
                file_info = response.json()
                return file_info
        except httpx.HTTPStatusError as e:
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
