from typing import Literal, Optional
from urllib.parse import urlparse

from .base_downloader import BaseDownloader
from .bilibili_downloader import BilibiliDownloader
from .youtube_downloader import YouTubeDownloader

Platform = Literal["bilibili", "youtube", "unknown"]


class DownloaderFactory:
    """Downloader factory class"""

    @classmethod
    def create_downloader(cls, url: str, video_dl_base_url: Optional[str] = None) -> BaseDownloader:
        """
        Create corresponding downloader based on URL

        Args:
            url: Video URL
            video_dl_base_url: Base URL for yt-dlp service. If None, falls back to local yt-dlp

        Returns:
            BaseDownloader instance
        """
        platform: Platform = cls.get_platform(url)

        if platform == "youtube":
            return YouTubeDownloader(video_dl_base_url)
        elif platform == "bilibili":
            return BilibiliDownloader(video_dl_base_url)
        else:
            return YouTubeDownloader(video_dl_base_url)

    @classmethod
    def get_platform(cls, url: str) -> Platform:
        """Get platform name from URL"""
        domain = urlparse(url).netloc.lower()

        if 'youtube.com' in domain or 'youtu.be' in domain:
            return 'youtube'
        elif 'bilibili.com' in domain or 'b23.tv' in domain:
            return 'bilibili'
        else:
            return 'unknown'
