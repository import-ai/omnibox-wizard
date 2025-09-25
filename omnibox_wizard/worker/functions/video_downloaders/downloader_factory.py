from typing import Literal
from urllib.parse import urlparse

from .base_downloader import BaseDownloader
from .bilibili_downloader import BilibiliDownloader
from .youtube_downloader import YouTubeDownloader

Platform = Literal["bilibili", "youtube", "unknown"]


class DownloaderFactory:
    """Downloader factory class"""

    @classmethod
    def create_downloader(cls, url: str) -> BaseDownloader:
        """Create corresponding downloader based on URL"""
        platform: Platform = cls.get_platform(url)

        if platform == "youtube":
            return YouTubeDownloader()
        elif platform == "bilibili":
            return BilibiliDownloader()
        else:
            return YouTubeDownloader()

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
