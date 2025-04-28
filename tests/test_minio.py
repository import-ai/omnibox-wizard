import os
import tempfile

import pytest
from dotenv import load_dotenv
from minio import Minio

from tests.helper.fixture import minio_endpoint

load_dotenv()


@pytest.fixture(scope='function')
def client(minio_endpoint: str) -> Minio:
    client = Minio(
        endpoint=os.environ['OBW_TASK_MINIO_ENDPOINT'],
        access_key=os.environ['OBW_TASK_MINIO_ACCESS_KEY'],
        secret_key=os.environ['OBW_TASK_MINIO_SECRET_KEY'],
        secure=False
    )

    return client


@pytest.fixture(scope='function')
def bucket(client: Minio) -> str:
    bucket: str = os.environ['OBW_TASK_MINIO_BUCKET']

    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)
    return bucket


def test_upload_file(client: Minio, bucket: str):
    with tempfile.TemporaryDirectory() as temp_dir:
        source_content: str = "Hello, MinIO!\n"
        source_file = os.path.join(temp_dir, "test_upload.txt")
        object_name = "upload/uploaded_test.txt"
        with open(source_file, "w") as f:
            f.write(source_content)

        client.fput_object(bucket, object_name, source_file)
        print(f"Uploaded '{source_file}' as '{object_name}' in bucket '{bucket}'.")

        download_path = os.path.join(temp_dir, "downloaded_test.txt")
        client.fget_object(bucket, object_name, download_path)
        print(f"Downloaded '{object_name}' as '{download_path}'.")

        with open(download_path, "r") as f:
            print("Downloaded file content:")
            downloaded_content: str = f.read()
            print(downloaded_content)

        assert downloaded_content == source_content
