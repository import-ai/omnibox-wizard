import mimetypes
import os
import tempfile

import pytest
from dotenv import load_dotenv

from common import project_root
from tests.helper.backend_client import BackendClient
from tests.helper.fixture import backend_client
from wizard.entity import Task
from wizard.wand.functions.file_reader import Convertor
from wizard.wand.worker import Worker

load_dotenv()


@pytest.fixture(scope="function")
def uploaded_file(backend_client: BackendClient) -> dict:
    with tempfile.TemporaryDirectory() as temp_dir:
        filepath: str = os.path.join(temp_dir, 'test.md')
        with open(filepath, 'w') as f:
            f.write('# Hello Markdown\n\nHello World!\n')
        mimetype, _ = mimetypes.guess_type(filepath)
        parent_id: str = backend_client.parent_id('private')

        with open(filepath, 'rb') as f:
            response = backend_client.post(f'/api/v1/namespaces/{backend_client.namespace_id}/resources/files', files={
                "file": (filepath, f, mimetype)
            }, data={
                'namespace_id': backend_client.namespace_id,
                'parent_id': parent_id
            })
            json_response: dict = response.json()
        yield {'resource_id': json_response['id'], 'filepath': filepath}


def test_download_file(backend_client: BackendClient, uploaded_file: dict):
    resource_id: str = uploaded_file['resource_id']
    filepath: str = uploaded_file['filepath']
    with backend_client.stream(
            'GET', f'/api/v1/namespaces/{backend_client.namespace_id}/resources/files/{resource_id}') as response:
        response.raise_for_status()
        content_disposition: str = response.headers.get('Content-Disposition')
        filename: str = content_disposition.split('filename="')[-1].rstrip('"')
        with tempfile.TemporaryDirectory() as temp_dir:
            downloaded_filepath = os.path.join(temp_dir, filename)
            with open(downloaded_filepath, 'wb') as f:
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
        input={
            "url": uploaded_file
        }
    )
    processed_task: Task = await worker.process_task(task, worker.get_trace_info(task))
    print(processed_task.output["markdown"])


@pytest.fixture(scope="function")
def convertor() -> Convertor:
    return Convertor(office_operator_base_url=os.environ["OBW_TASK_OFFICE_OPERATOR_BASE_URL"])


@pytest.mark.parametrize("filename", [
    "example.doc"
])
async def test_convertor(convertor: Convertor, filename):
    filepath: str = project_root.path(os.path.join("tests/resources/files", filename))
    markdown: str = await convertor.convert(filepath, '.doc')
    print(markdown)
