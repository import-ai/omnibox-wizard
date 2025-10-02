from omnibox_wizard.worker.functions.video_downloaders.bilibili_downloader import BilibiliDownloader
from omnibox_wizard.worker.functions.video_downloaders.downloader_factory import DownloaderFactory
from omnibox_wizard.worker.functions.video_downloaders.youtube_downloader import YouTubeDownloader


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

    def test_create_youtube_downloader_with_service(self):
        video_dl_base_url = "http://localhost:8000"
        downloader = DownloaderFactory.create_downloader("https://www.youtube.com/watch?v=test", video_dl_base_url)
        assert isinstance(downloader, YouTubeDownloader)
        assert downloader.video_dl_base_url == video_dl_base_url
        assert downloader.video_dl_client is not None

    def test_create_bilibili_downloader_with_service(self):
        video_dl_base_url = "http://localhost:8000"
        downloader = DownloaderFactory.create_downloader("https://www.bilibili.com/video/BV123", video_dl_base_url)
        assert isinstance(downloader, BilibiliDownloader)
        assert downloader.video_dl_base_url == video_dl_base_url
        assert downloader.video_dl_client is not None
