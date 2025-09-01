import pytest
from omnibox_wizard.worker.functions.video_downloaders.downloader_factory import DownloaderFactory
from omnibox_wizard.worker.functions.video_downloaders.youtube_downloader import YouTubeDownloader
from omnibox_wizard.worker.functions.video_downloaders.bilibili_downloader import BilibiliDownloader
from unittest.mock import patch


class TestDownloaderFactory:
    
    def test_get_platform_youtube(self):
        assert DownloaderFactory.get_platform("https://www.youtube.com/watch?v=test123") == "youtube"
        assert DownloaderFactory.get_platform("https://youtu.be/test123") == "youtube"
        assert DownloaderFactory.get_platform("http://youtube.com/watch?v=test") == "youtube"
        assert DownloaderFactory.get_platform("https://m.youtube.com/watch?v=test") == "youtube"
    
    def test_get_platform_bilibili(self):
        assert DownloaderFactory.get_platform("https://www.bilibili.com/video/BV1234567890") == "bilibili"
        assert DownloaderFactory.get_platform("https://bilibili.com/video/av123456") == "bilibili"
        assert DownloaderFactory.get_platform("https://b23.tv/abcdefg") == "bilibili"
        assert DownloaderFactory.get_platform("http://bilibili.com/video/BV123") == "bilibili"
    
    def test_get_platform_unknown(self):
        assert DownloaderFactory.get_platform("https://www.example.com/video") == "unknown"
        assert DownloaderFactory.get_platform("http://vimeo.com/123456") == "unknown"
    
    @patch('omnibox_wizard.worker.functions.video_downloaders.youtube_downloader.subprocess.run')
    def test_create_youtube_downloader(self, mock_subprocess):
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "yt-dlp 2024.01.01"
        
        downloader = DownloaderFactory.create_downloader("https://www.youtube.com/watch?v=test")
        assert isinstance(downloader, YouTubeDownloader)
        mock_subprocess.assert_called_once()
    
    @patch('omnibox_wizard.worker.functions.video_downloaders.bilibili_downloader.subprocess.run')
    def test_create_bilibili_downloader(self, mock_subprocess):
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "yt-dlp 2024.01.01"
        
        downloader = DownloaderFactory.create_downloader("https://www.bilibili.com/video/BV123")
        assert isinstance(downloader, BilibiliDownloader)
        mock_subprocess.assert_called_once()
    
    @patch('omnibox_wizard.worker.functions.video_downloaders.youtube_downloader.subprocess.run')
    def test_create_default_downloader(self, mock_subprocess):
        mock_subprocess.return_value.returncode = 0
        mock_subprocess.return_value.stdout = "yt-dlp 2024.01.01"
        
        downloader = DownloaderFactory.create_downloader("https://www.example.com/video")
        assert isinstance(downloader, YouTubeDownloader)
        mock_subprocess.assert_called_once()