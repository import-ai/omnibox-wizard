"""Base class for file uploaders"""
from abc import ABC, abstractmethod
from pathlib import Path


class FileUploader(ABC):
    """Abstract base class for file uploaders that provide public URLs"""

    @abstractmethod
    async def upload(self, file_path: str) -> str:
        """
        Upload a file and return a publicly accessible URL

        Args:
            file_path: Path to the local file to upload

        Returns:
            Public URL to access the uploaded file

        Raises:
            RuntimeError: If upload fails
        """
        pass

    @abstractmethod
    async def cleanup(self, url: str) -> None:
        """
        Clean up the uploaded file (if supported by the service)

        Args:
            url: The URL returned by upload()
        """
        pass

    def _validate_file(self, file_path: str) -> None:
        """Validate that file exists and is readable"""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        if not path.is_file():
            raise ValueError(f"Not a file: {file_path}")
