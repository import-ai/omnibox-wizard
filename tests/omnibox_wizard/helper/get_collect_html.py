import base64
import gzip
import hashlib
import hmac
import os
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import urlparse

import httpx


def get_collect_html(object_path: str) -> str:
    s3_url = os.environ.get("TEST_S3_URL")
    if not s3_url:
        raise RuntimeError("TEST_S3_URL environment variable is not set")

    parsed = urlparse(s3_url)
    config = {
        'endpoint': f"{parsed.scheme}://{parsed.hostname}:{parsed.port}" if parsed.port else f"{parsed.scheme}://{parsed.hostname}",
        'access_key': parsed.username,
        'secret_key': parsed.password,
        'bucket_name': parsed.path.lstrip('/'),
        'secure': parsed.scheme == 'https'
    }

    minio_path = f"/{config['bucket_name']}/{object_path}"
    file_url = f"{config['endpoint']}{minio_path}"

    # Date header in RFC 2822 (like `date -R`)
    date_str = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S %z")
    content_type = "application/zstd"

    # Build AWS v2 signature
    sig_string = f"GET\n\n{content_type}\n{date_str}\n{minio_path}"
    signature = base64.b64encode(
        hmac.new(config['secret_key'].encode(), sig_string.encode(), hashlib.sha1).digest()
    ).decode()

    headers = {
        "Host": parsed.hostname,
        "Date": date_str,
        "Content-Type": content_type,
        "Authorization": f"AWS {config['access_key']}:{signature}",
    }

    with httpx.Client() as client:
        response = client.get(file_url, headers=headers)
        response.raise_for_status()
        compressed_data = response.content

    with gzip.GzipFile(fileobj=BytesIO(compressed_data)) as gz_file:
        decompressed_bytes = gz_file.read()
        decompressed_string = decompressed_bytes.decode("utf-8")
    return decompressed_string
