"""S3-compatible object storage uploader implementation"""
import logging
import uuid
from datetime import datetime
from pathlib import Path

import boto3
from botocore.config import Config

from .base_uploader import FileUploader

logger = logging.getLogger(__name__)


class S3Uploader(FileUploader):
    """
    File uploader using S3-compatible object storage

    Supports:
    - AWS S3
    - Aliyun OSS
    - Tencent COS
    - MinIO
    - Any S3-compatible service

    Requires: boto3
    """

    def __init__(
            self,
            bucket: str,
            access_key: str = None,
            secret_key: str = None,
            endpoint_url: str = None,
            prefix: str = "temp-uploads",
            expire_hours: int = 24
    ):
        """
        Initialize S3 uploader

        Args:
            bucket: S3/OSS bucket name
            access_key: Access key ID
            secret_key: Secret access key
            session_token: Session token (optional, for temporary credentials)
            endpoint_url: Custom endpoint URL (e.g., https://oss-cn-hangzhou.aliyuncs.com)
            prefix: Key prefix for uploaded files
            expire_hours: Hours before presigned URL expires
        """

        self.bucket = bucket
        self.prefix = prefix.rstrip('/')
        self.expire_hours = expire_hours

        # Prepare boto3 client configuration
        # Use virtual addressing style for better compatibility with Aliyun OSS and other services
        boto_config = Config(
            s3={"addressing_style": "virtual"},
            signature_version='v4'
        )

        client_kwargs = {
            'aws_access_key_id': access_key,
            'aws_secret_access_key': secret_key,
            'config': boto_config
        }

        # Add endpoint URL if provided (required for non-AWS services)
        if endpoint_url:
            client_kwargs['endpoint_url'] = endpoint_url

        self.s3_client = boto3.client('s3', **client_kwargs)
        self.uploaded_keys = []

    async def upload(self, file_path: str) -> str:
        """
        Upload file to S3 and return presigned URL

        Args:
            file_path: Path to the local file

        Returns:
            Presigned URL to access the file

        Raises:
            RuntimeError: If upload fails
        """
        self._validate_file(file_path)

        path = Path(file_path)
        filename = path.name

        # Generate unique key
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        unique_id = uuid.uuid4().hex[:8]
        key = f"{self.prefix}/{timestamp}_{unique_id}_{filename}"

        try:
            # Upload file
            self.s3_client.upload_file(
                str(path),
                self.bucket,
                key,
                ExtraArgs={'ContentType': self._guess_content_type(filename)}
            )

            # Generate presigned URL
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={
                    'Bucket': self.bucket,
                    'Key': key
                },
                ExpiresIn=self.expire_hours * 3600
            )

            self.uploaded_keys.append(key)
            logger.info(f"Successfully uploaded {filename} to S3: {key}")
            return url

        except Exception as e:
            raise RuntimeError(f"Failed to upload file to S3: {str(e)}")

    async def cleanup(self, url: str) -> None:
        """
        Delete uploaded files from S3

        Args:
            url: The URL (used to extract key)
        """
        # Extract key from URL if possible, or delete all uploaded keys
        if self.uploaded_keys:
            try:
                for key in self.uploaded_keys:
                    self.s3_client.delete_object(Bucket=self.bucket, Key=key)
                    logger.info(f"Deleted {key} from S3")
                self.uploaded_keys.clear()
            except Exception as e:
                logger.warning(f"Failed to cleanup S3 files: {str(e)}")

    @staticmethod
    def _guess_content_type(filename: str) -> str:
        """Guess content type from filename"""
        import mimetypes
        content_type, _ = mimetypes.guess_type(filename)
        return content_type or 'application/octet-stream'
