import os
import tempfile

import httpx

from omnibox_wizard.common.trace_info import TraceInfo
from omnibox_wizard.wizard.config import OpenAIConfig
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task, Image
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.worker.functions.file_readers.audio_reader import ASRClient, M4AConvertor
from omnibox_wizard.worker.functions.file_readers.office_reader import OfficeReader, OfficeOperatorClient
from omnibox_wizard.worker.functions.file_readers.pdf_reader import PDFReader
from omnibox_wizard.worker.functions.file_readers.utils import guess_extension


class Convertor:
    def __init__(
            self,
            office_operator_base_url: str,
            asr_config: OpenAIConfig,
            pdf_reader_base_url: str,
    ):
        self.office_reader: OfficeReader = OfficeReader()
        self.office_operator_base_url: str = office_operator_base_url
        self.asr_client: ASRClient = ASRClient(
            model=asr_config.model,
            base_url=asr_config.base_url,
            headers={"Authorization": f"Bearer {asr_config.api_key}"},
        )
        self.pdf_reader: PDFReader = PDFReader(base_url=pdf_reader_base_url)
        self.m4a_convertor: M4AConvertor = M4AConvertor()

    async def convert(self, filepath: str, mime_ext: str, mimetype: str) -> tuple[str, list[Image]]:
        if mime_ext in [".pptx", ".docx", ".ppt", ".doc"]:
            path = filepath
            if mime_ext in [".ppt", ".doc"]:
                path: str = filepath + "x"
                async with OfficeOperatorClient(base_url=self.office_operator_base_url) as client:
                    await client.migrate(filepath, mime_ext, path, mimetype)
            return self.office_reader.convert(path)
        elif mime_ext in [".pdf"]:
            return await self.pdf_reader.convert(filepath)
        elif mime_ext in [".md", ".plain"]:
            with open(filepath, 'r') as f:
                markdown: str = f.read()
        elif mime_ext in [".wav", ".mp3", ".pcm", ".opus", ".webm", ".m4a"]:
            if mime_ext == ".m4a":
                filepath = self.m4a_convertor.convert(filepath)
            markdown: str = await self.asr_client.transcribe(filepath, mimetype)
        else:
            raise ValueError(f"unsupported_type: {mime_ext}")
        return markdown, []


class FileReader(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.base_url: str = config.backend.base_url

        self.convertor: Convertor = Convertor(
            office_operator_base_url=config.task.office_operator_base_url,
            asr_config=config.task.asr,
            pdf_reader_base_url=config.task.pdf_reader_base_url,
        )

    async def download(self, resource_id: str, target: str):
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

        with tempfile.TemporaryDirectory() as temp_dir:
            local_path: str = os.path.join(temp_dir, filename)
            await self.download(resource_id, local_path)

            mime_ext: str | None = guess_extension(mimetype)

            try:
                markdown, images = await self.convertor.convert(local_path, mime_ext, mimetype)
            except ValueError:
                return {
                    "message": "unsupported_type",
                    "mime_ext": mime_ext,
                    "mimetype": mimetype,
                }

        result_dict: dict = {"title": title, "markdown": markdown} | ({"images": [
            image.model_dump(exclude_none=True) for image in images
        ]} if images else {})
        return result_dict
