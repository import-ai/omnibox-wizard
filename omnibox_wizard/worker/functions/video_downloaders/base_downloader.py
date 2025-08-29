from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class VideoInfo:
    """视频信息"""
    title: str
    duration: float
    video_id: str
    platform: str
    url: str
    description: str = ""
    uploader: str = ""
    upload_date: str = ""
    thumbnail_url: str = ""


@dataclass
class DownloadResult:
    """下载结果"""
    audio_path: str
    video_path: Optional[str]
    video_info: VideoInfo


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
    def get_video_info(self, url: str) -> VideoInfo:
        """Get video information without downloading"""
        pass  