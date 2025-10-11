from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel


class VideoInfo(BaseModel):
    title: str = ""
    duration: float = 0
    video_id: str = ""
    platform: str = ""
    url: str = ""
    description: str = ""
    uploader: str = ""
    upload_date: str = ""
    thumbnail_url: str = ""
    real_url: str = ""


class DownloadResult(BaseModel):
    audio_path: str | None = None
    video_path: Optional[str] = None
    video_info: VideoInfo = VideoInfo()
    chapters: list[dict] = []
    subtitles: dict = {}


class BaseDownloader(ABC):
    """Video downloader base class"""

    @abstractmethod
    async def download(self, url: str, output_dir: str, download_video: bool = False) -> DownloadResult:
        """
        Download video/audio
        
        Args:
            url: Video link
            output_dir: Directory to save downloaded files
            download_video: Whether to download video file (for screenshots, etc.)
            
        Returns:
            DownloadResult: Download result
        """
        pass

    @abstractmethod
    def get_video_info(self, url: str, video_id: str) -> VideoInfo:
        """Get video information without downloading"""
        pass
