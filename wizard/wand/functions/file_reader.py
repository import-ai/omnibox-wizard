import io
import mimetypes
import os
import tempfile

import httpcore
import httpx
from markitdown import MarkItDown

from common.trace_info import TraceInfo
from wizard.config import WorkerConfig, OpenAIConfig
from wizard.entity import Task
from wizard.wand.functions.base_function import BaseFunction


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


class ASRClient(httpx.AsyncClient):

    def __init__(self, model: str, *args, **kwargs):
        self.model: str = model
        super().__init__(*args, **kwargs)

    async def transcribe(self, file_path: str, mimetype: str, retry_cnt: int = 3) -> str:
        with open(file_path, "rb") as f:
            bytes_content: bytes = f.read()

        for i in range(retry_cnt):
            try:
                response: httpx.Response = await self.post(
                    "/audio/transcriptions",
                    files={"file": (file_path, io.BytesIO(bytes_content), mimetype)},
                    data={"model": self.model}
                )
                assert response.is_success, response.text
                return response.json()["text"]
            except (TimeoutError, httpcore.ReadTimeout, httpx.ReadTimeout):
                continue
        raise RuntimeError("ASR transcription failed after retries")


class Convertor:
    def __init__(self, office_operator_base_url: str, asr_config: OpenAIConfig):
        self.markitdown: MarkItDown = MarkItDown()
        self.office_operator_base_url: str = office_operator_base_url
        self.asr_client: ASRClient = ASRClient(
            model=asr_config.model,
            base_url=asr_config.base_url,
            headers={"Authorization": f"Bearer {asr_config.api_key}"},
        )

    async def convert(self, filepath: str, mime_ext: str, mimetype: str) -> str:
        if mime_ext in [".pptx", ".docx", ".pdf", ".ppt", ".doc"]:
            path = filepath
            if mime_ext in [".ppt", ".doc"]:
                path: str = filepath + "x"
                async with OfficeOperatorClient(base_url=self.office_operator_base_url) as client:
                    await client.migrate(filepath, mime_ext, path, mimetype)
            result = self.markitdown.convert(path)
            markdown: str = result.text_content
        elif mime_ext in [".md", ".txt"]:
            with open(filepath, 'r') as f:
                markdown: str = f.read()
        elif mime_ext in [".wav", ".mp3", ".pcm", ".opus", ".webm"]:
            markdown: str = await self.asr_client.transcribe(filepath, mimetype)
        else:
            raise ValueError(f"unsupported_type: {mime_ext}")
        return markdown


class FileReader(BaseFunction):
    def __init__(self, config: WorkerConfig):
        self.base_url: str = config.backend.base_url

        self.mimetype_mapping: dict[str, str] = {
            "text/x-markdown": ".md"
        }
        self.convertor: Convertor = Convertor(config.task.office_operator_base_url, config.task.asr)

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
                markdown: str = await self.convertor.convert(local_path, mime_ext, mimetype)
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
