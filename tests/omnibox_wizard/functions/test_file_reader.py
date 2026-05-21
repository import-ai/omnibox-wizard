import mimetypes
import os
import tempfile

import pytest
from dotenv import load_dotenv

from common.trace_info import TraceInfo
from common import project_root
from wizard_common.worker.entity import Task
from omnibox_wizard.worker.functions.file_reader import (
    Convertor,
    FileContentTooLongError,
    FileReader,
    MAX_FILE_CONTENT_LENGTH,
    format_content_too_long_message,
)
from omnibox_wizard.worker.worker import Worker
from tests.omnibox_wizard.helper.backend_client import BackendClient
from omnibox_wizard.worker.config import WorkerConfig

load_dotenv()


@pytest.fixture(scope="function")
def uploaded_file(backend_client: BackendClient) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        filepath: str = os.path.join(temp_dir, "test.md")
        with open(filepath, "w") as f:
            f.write("# Hello Markdown\n\nHello World!\n")
        mimetype, _ = mimetypes.guess_type(filepath)
        parent_id: str = backend_client.parent_id("private")

        with open(filepath, "rb") as f:
            response = backend_client.post(
                f"/api/v1/namespaces/{backend_client.namespace_id}/resources/files",
                files={"file": (filepath, f, mimetype)},
                data={
                    "namespace_id": backend_client.namespace_id,
                    "parent_id": parent_id,
                },
            )
            json_response: dict = response.json()
        yield {"resource_id": json_response["id"], "filepath": filepath}


def test_download_file(backend_client: BackendClient, uploaded_file: dict):
    resource_id: str = uploaded_file["resource_id"]
    filepath: str = uploaded_file["filepath"]
    with backend_client.stream(
        "GET",
        f"/api/v1/namespaces/{backend_client.namespace_id}/resources/files/{resource_id}",
    ) as response:
        response.raise_for_status()
        content_disposition: str = response.headers.get("Content-Disposition")
        filename: str = content_disposition.split('filename="')[-1].rstrip('"')
        with tempfile.TemporaryDirectory() as temp_dir:
            downloaded_filepath = os.path.join(temp_dir, filename)
            with open(downloaded_filepath, "wb") as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
            with open(filepath) as f:
                raw_content = f.read()
            with open(downloaded_filepath) as f:
                downloaded_content = f.read()

            assert raw_content == downloaded_content


async def test_file_reader(worker: Worker, uploaded_file: str):
    task: Task = Task(
        task_id="test",
        priority=5,
        namespace_id="test",
        user_id="test",
        function="file_reader",
        input={"url": uploaded_file},
    )
    processed_task: Task = await worker.process_task(task, worker.get_trace_info(task))
    print(processed_task.output["markdown"])


@pytest.fixture(scope="function")
def convertor(remote_worker_config: WorkerConfig) -> Convertor:
    return Convertor(
        office_operator_base_url=os.environ["OBW_TASK_OFFICE_OPERATOR_BASE_URL"],
        docling_base_url=os.environ["OBW_TASK_DOCLING_BASE_URL"],
    )


@pytest.mark.parametrize(
    "filename",
    [
        # "example.doc",
        # "test.mp3",
        # "test.docx",
        "file_reader/example.txt",
    ],
)
async def test_convertor(convertor: Convertor, filename, trace_info: TraceInfo):
    filepath: str = project_root.path(
        os.path.join("tests/omnibox_wizard/resources/files", filename)
    )
    markdown, images, d = await convertor.convert(filepath)
    print(markdown)


async def test_convertor_rejects_content_above_system_limit(tmp_path):
    length = MAX_FILE_CONTENT_LENGTH + 1
    filepath = tmp_path / "large.txt"
    filepath.write_text("a" * length)

    with pytest.raises(FileContentTooLongError) as exc:
        await Convertor().convert(str(filepath))

    assert exc.value.length == length


@pytest.mark.parametrize(
    ("language", "expected"),
    [
        (
            "zh-CN",
            "当前文件内容（32769 字符）超过系统可处理上限"
            "（32768 字符），请尝试拆分文档后重新上传。",
        ),
        (
            "en-US",
            "The current file content (32769 characters) exceeds the system "
            "processing limit (32,768 characters). Please try splitting the "
            "document and uploading it again.",
        ),
        (
            None,
            "当前文件内容（32769 字符）超过系统可处理上限"
            "（32768 字符），请尝试拆分文档后重新上传。",
        ),
    ],
)
async def test_file_reader_returns_localized_content_limit_message(
    language: str | None,
    expected: str,
):
    length = MAX_FILE_CONTENT_LENGTH + 1

    class TooLongConvertor:
        async def convert(self, *args, **kwargs):
            raise FileContentTooLongError(length)

    async def download(namespace_id: str, resource_id: str, target: str):
        return None

    reader = object.__new__(FileReader)
    reader.convertor = TooLongConvertor()
    reader.download = download

    task_input = {
        "title": "Large file",
        "original_name": "large.txt",
        "resource_id": "resource-id",
        "mimetype": "text/plain",
    }
    if language:
        task_input["language"] = language
    task = Task(
        id="test",
        priority=5,
        namespace_id="test",
        user_id="test",
        function="file_reader",
        input=task_input,
    )

    result = await reader.run(task, None)

    assert result == {
        "title": "Large file",
        "markdown": expected,
        "skip_tasks": True,
    }
    assert "Content too long" not in result["markdown"]
    assert "`" not in result["markdown"]


def test_format_content_too_long_message_supports_en_and_zh():
    length = MAX_FILE_CONTENT_LENGTH + 19

    assert format_content_too_long_message(length, "en") == (
        "The current file content (32787 characters) exceeds the system "
        "processing limit (32,768 characters). Please try splitting the document "
        "and uploading it again."
    )
    assert format_content_too_long_message(length, "zh") == (
        "当前文件内容（32787 字符）超过系统可处理上限"
        "（32768 字符），请尝试拆分文档后重新上传。"
    )
