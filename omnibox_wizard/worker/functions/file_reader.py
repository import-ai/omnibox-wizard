import os
import tempfile
from pathlib import Path

import httpx
from httpx import AsyncHTTPTransport, Timeout

from common.exception import CommonException
from common.plain_reader import read_text_file
from common.trace_info import TraceInfo
from omnibox_wizard.worker.config import WorkerConfig
from omnibox_wizard.worker.entity import Task, Image
from omnibox_wizard.worker.functions.base_function import BaseFunction
from omnibox_wizard.worker.functions.file_readers.md_reader import MDReader
from omnibox_wizard.worker.functions.file_readers.office_reader import (
    OfficeReader,
    OfficeOperatorClient,
)


class Convertor:
    def __init__(
        self,
        docling_base_url: str | None = None,
        office_operator_base_url: str | None = None,
    ):
        self.docling_base_url: str | None = docling_base_url
        self.office_operator_base_url: str | None = office_operator_base_url
        self.md_reader: MDReader = MDReader()

        self.supported_extensions = [".md", ".txt"]
        if self.docling_base_url:
            self.supported_extensions.extend([".pptx", ".docx"])
            if self.office_operator_base_url:
                self.supported_extensions.extend([".ppt", ".doc"])

    async def convert(
        self, filepath: str, *args, **kwargs
    ) -> tuple[str, list[Image], dict]:
        ext = Path(filepath).suffix.lower()

        images: list[Image] = []
        metadata: dict[str, str] = {}

        if ext in [".pptx", ".docx", ".ppt", ".doc"] and self.docling_base_url:
            path = filepath
            if ext in [".ppt", ".doc"]:
                if not self.office_operator_base_url:
                    raise ValueError(f"unsupported_type: {ext}")
                async with OfficeOperatorClient(
                    base_url=self.office_operator_base_url,
                    transport=AsyncHTTPTransport(retries=3),
                    timeout=30,
                ) as client:
                    path = await client.migrate(filepath)
            async with OfficeReader(
                base_url=self.docling_base_url,
                transport=AsyncHTTPTransport(retries=3),
                timeout=30,
            ) as client:
                markdown, images = await client.convert(path)
        elif ext in [".md"]:
            markdown, images, metadata = self.md_reader.convert(filepath)
        elif ext in [".txt"]:
            markdown = read_text_file(filepath)
        else:
            raise CommonException(400, f"Unsupported type: {ext}")
        if (length := len(markdown)) > 32 * 1024:
            raise CommonException(400, f"Content too long: {length}")
        return markdown, images, metadata


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
            async with httpx.AsyncClient(
                base_url=self.base_url, transport=AsyncHTTPTransport(retries=3)
            ) as client:
                response = await client.get(
                    f"/internal/api/v1/namespaces/{namespace_id}/resources/{resource_id}/file"
                )
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

        async with httpx.AsyncClient(
            transport=AsyncHTTPTransport(retries=3), timeout=Timeout(30)
        ) as client:
            async with client.stream("GET", file_info["internal_url"]) as response:
                response.raise_for_status()
                with open(target, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)

    async def download_old(self, resource_id: str, target: str):
        async with httpx.AsyncClient(base_url=self.base_url) as client:
            async with client.stream(
                "GET", f"/internal/api/v1/resources/files/{resource_id}"
            ) as response:
                response.raise_for_status()
                with open(target, "wb") as f:
                    async for chunk in response.aiter_bytes():
                        f.write(chunk)

    async def run(self, task: Task, trace_info: TraceInfo) -> dict:
        task_input: dict = task.input

        title: str = task_input["title"]
        filename: str = task_input.get("filename", task_input["original_name"])
        resource_id: str = task_input["resource_id"]
        mimetype: str = task_input["mimetype"]

        # Extract additional parameters for video processing
        language: str = task_input.get("language", "zh")
        style: str = task_input.get("style", "Concise Style")
        include_screenshots: bool = task_input.get("include_screenshots", True)
        include_links: bool = task_input.get("include_links", False)

        with tempfile.TemporaryDirectory() as temp_dir:
            local_path: str = os.path.join(temp_dir, filename)
            await self.download(task.namespace_id, resource_id, local_path)

            try:
                # Pass additional parameters for video processing
                convert_params = {
                    "language": language,
                    "style": style,
                    "include_screenshots": include_screenshots,
                    "include_links": include_links,
                }
                markdown, images, metadata = await self.convertor.convert(
                    local_path, **convert_params
                )
            except ValueError:
                return {
                    "message": "unsupported_type",
                    "mimetype": mimetype,
                }
            except CommonException as e:
                return {
                    "title": title,
                    "markdown": f"`{e.error}`",
                    "skip_tasks": True,
                }

        result_dict: dict = {
            "title": (metadata or {}).pop("title", None) or title,
            "markdown": markdown,
        }
        if images:
            result_dict["images"] = [
                image.model_dump(exclude_none=True) for image in images
            ]
        if metadata:
            result_dict["metadata"] = metadata

        # Add extract_tags to next_tasks
        next_tasks = []
        extract_tags_task = task.create_next_task(
            function="extract_tags",
            input={"text": markdown},
        )
        next_tasks.append(extract_tags_task.model_dump())

        # Add generate_title for open_api uploads
        if task.payload and task.payload.get("source") == "open_api":
            generate_title_task = task.create_next_task(
                function="generate_title",
                input={"text": markdown},
            )
            next_tasks.append(generate_title_task.model_dump())

        if next_tasks:
            result_dict["next_tasks"] = next_tasks

        return result_dict
