import os
import tempfile

from markitdown import MarkItDown
from minio import Minio

from common.trace_info import TraceInfo
from wizard.config import MinioConfig
from wizard.entity import Task
from wizard.wand.functions.base_function import BaseFunction


class FileReader(BaseFunction):
    def __init__(self, config: MinioConfig):
        self.markitdown: MarkItDown = MarkItDown()
        self.minio: Minio = Minio(
            endpoint=config.endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=False
        )
        self.bucket: str = config.bucket

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        task_input: dict = task.input
        url: str = task_input["url"]

        basedir: str = os.path.dirname(url) + os.path.sep
        name, ext = os.path.splitext(os.path.basename(url))
        name = name.lstrip(basedir)
        ext = ext.lstrip(".")

        with tempfile.TemporaryDirectory() as temp_dir:
            local_path: str = os.path.join(temp_dir, name + "." + ext)
            self.minio.fget_object(self.bucket, url, local_path)

            if ext in ["pptx", "docx", "pdf"]:
                result = self.markitdown.convert(local_path)
                markdown: str = result.text_content
            else:
                raise ValueError(f"Unsupported file type: {ext}")

        result_dict: dict = {
            "url": url,
            "title": name,
            "markdown": markdown
        }
        return result_dict
