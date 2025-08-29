from urllib.parse import urlparse

from .base_downloader import BaseDownloader
from .youtube_downloader import YouTubeDownloader
from .bilibili_downloader import BilibiliDownloader


class DownloaderFactory:
    """Downloader factory class"""
    
    @staticmethod
    def create_downloader(url: str) -> BaseDownloader:
        """Create corresponding downloader based on URL"""
        domain = urlparse(url).netloc.lower()
        
        if 'youtube.com' in domain or 'youtu.be' in domain:
            return YouTubeDownloader()
        elif 'bilibili.com' in domain or 'b23.tv' in domain:
            return BilibiliDownloader()
        else:
            return YouTubeDownloader()
    
    @staticmethod
    def get_platform(url: str) -> str:
        """Get platform name from URL"""
        domain = urlparse(url).netloc.lower()
        
        if 'youtube.com' in domain or 'youtu.be' in domain:
            return 'youtube'
        elif 'bilibili.com' in domain or 'b23.tv' in domain:
            return 'bilibili'
        else:
            return 'unknown'